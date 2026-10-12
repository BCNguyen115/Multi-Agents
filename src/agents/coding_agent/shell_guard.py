"""A filter for the shell commands the coding agent asks to run (``run_shell``). It catches the mistakes and the obvious abuses, and it gives
the model a clear reason it can act on. It is NOT the security boundary: a shell command can always be written in a way a text filter does not
foresee (a Python one-liner, a script the model just wrote). The boundary is the container: no network, a read-only root filesystem, writes
only to /work and /tmp, no capabilities, a non-root user, memory / process / time limits, and the signing key kept out of the environment.

Blocked: network tools and package installs (there is no network, and a clear message beats a hang); privilege and process-control tools; disk
tools; detaching or scheduling; nested shells and eval (they would hide a command from this filter); git commands that change anything
(commits are made by a person); any reference to the .git directory, /proc, /sys, /dev; recursive removal of the workspace root, of anything
outside it, or of a bare wildcard; writes (cp, mv, redirection, sed -i, ...) outside the workspace and /tmp.
"""

from __future__ import annotations

import posixpath
import re
import shlex

MAX_COMMAND_CHARS = 4000

NETWORK = {"curl", "wget", "nc", "ncat", "netcat", "telnet", "ssh", "scp", "sftp", "ftp", "rsync", "nmap", "ping", "dig", "nslookup", "host", "socat", "traceroute"}
PRIVILEGE = {"sudo", "su", "doas", "chroot", "nsenter", "unshare", "mount", "umount", "docker", "podman", "systemctl", "service", "capsh", "setcap"}
DETACH = {"setsid", "nohup", "disown", "screen", "tmux", "at", "batch", "crontab", "daemonize"}
PROCESS_CONTROL = {"kill", "pkill", "killall", "xkill"}
DISK = {"dd", "mkfs", "fdisk", "parted", "shred", "mknod", "mkfifo", "losetup", "wipefs"}
OWNERSHIP = {"chown", "chgrp", "setfacl", "chattr"}
NESTED_SHELLS = {"sh", "bash", "zsh", "dash", "ksh", "csh", "tcsh", "fish", "eval", "exec", "source", "."}
WRAPPERS = {"env", "time", "nice", "ionice", "command", "stdbuf", "timeout", "xargs", "builtin"}
WRITERS = {"cp", "mv", "ln", "install", "tee", "touch", "mkdir", "chmod", "truncate"}
REMOVERS = {"rm", "rmdir", "unlink"}
PACKAGE_MANAGERS = {
    "pip": {"install", "download", "wheel", "uninstall"}, "pip3": {"install", "download", "wheel", "uninstall"},
    "npm": {"install", "i", "ci", "add", "update", "publish", "uninstall"}, "yarn": {"install", "add", "upgrade", "remove"}, "pnpm": {"install", "i", "add", "update"},
    "gem": {"install"}, "cargo": {"install", "add", "fetch"}, "go": {"get", "install"}, "conda": {"install", "create"},
}
ANY_SUBCOMMAND = {"apt", "apt-get", "apk", "brew", "yum", "dnf", "npx", "pipx", "uv"}
READ_ONLY_GIT = {"status", "diff", "log", "show", "ls-files", "blame", "grep", "rev-parse", "describe", "shortlog", "cat-file", "ls-tree", "diff-tree", "show-ref"}
SEPARATORS = {";", "&&", "||", "|", "&", "|&", "(", ")", ";;"}
REDIRECTS = {">", ">>", ">|", "&>", "&>>", "<>"}
OUTPUT_SINKS = {"/dev/null", "/dev/stdout", "/dev/stderr"}
ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
GIT_DIR = re.compile(r"(^|/)\.git(/|$)")
SYSTEM_PATH = re.compile(r"^/(proc|sys|dev)(/|$)")
MODE = re.compile(r"^[0-7]{3,4}$|^[ugoa]*[+\-=][rwxXst]+(,[ugoa]*[+\-=][rwxXst]+)*$")
DESCRIPTOR = re.compile(r"^[0-9]*[<>]+&?[0-9-]*$")


class Blocked(ValueError):
    """The command was refused; the message says why and what to do instead."""


def _resolve(root: str, path: str) -> str:
    if path.startswith("~"):
        path = root + path[1:]
    return posixpath.normpath(path if posixpath.isabs(path) else posixpath.join(root, path))


def _inside(root: str, path: str) -> bool:
    """Is ``path`` (relative to ``root`` unless absolute, ``~`` = the workspace) inside the workspace or /tmp?"""
    full = _resolve(root, path)
    return full == root or full.startswith(root.rstrip("/") + "/") or full == "/tmp" or full.startswith("/tmp/")


def _target_ok(root: str, arg: str) -> bool:
    """A write target is acceptable when it is inside the workspace or /tmp. A variable is tolerated only in the FINAL path component
    (`build/out_$i.txt`): the directory is then literal and checked; a variable earlier in the path could be `..` and is refused."""
    if "`" in arg:
        return False
    if "$" in arg:
        directory, _, _ = arg.rpartition("/")
        if "$" in directory or arg.startswith("$"):
            return False
        return _inside(root, directory or ".")
    return _inside(root, arg)


def _path_like(arg: str) -> bool:
    return "/" in arg or arg.startswith(("~", ".")) or arg == ".."


def _check_path_access(arg: str) -> None:
    if GIT_DIR.search(arg):
        raise Blocked("the .git directory is off limits; use `git diff` / `git log` to look at history, and the file tools to change files")
    if SYSTEM_PATH.match(arg) and arg not in OUTPUT_SINKS and arg != "/dev/zero":
        raise Blocked(f"{arg.split('/')[1]!r} paths are off limits")


def _removal(root: str, args: list[str]) -> None:
    for target in (a for a in args if not a.startswith("-")):
        if "$" in target or "`" in target:
            raise Blocked("rm needs literal paths, not variables or substitutions")
        if target in {"*", ".*", ".", "..", "/", "./", "./*", "../*"} or target.startswith("~"):
            raise Blocked(f"refusing to remove {target!r}: name the specific files or directory inside the workspace")
        head = re.split(r"[*?\[]", target, maxsplit=1)[0]
        if head != target and (head in ("", "./") or _resolve(root, head) == root):
            raise Blocked(f"refusing a wildcard at the top of the workspace ({target!r}); remove a named subdirectory instead")
        full = _resolve(root, target)
        if full == root:
            raise Blocked("refusing to remove the workspace itself")
        if full in {"/tmp"} or not _inside(root, target):
            raise Blocked(f"refusing to remove {target!r}: only paths inside the workspace")
        if full == posixpath.join(root, ".git") or full.startswith(posixpath.join(root, ".git") + "/"):
            raise Blocked("never remove .git")


def _find(root: str, args: list[str]) -> None:
    if any(a in {"-exec", "-execdir", "-ok", "-okdir"} for a in args):
        raise Blocked("find -exec hides a command from the filter; pipe the names to xargs or use the file tools")
    if "-delete" in args:
        starts: list[str] = []
        for arg in args:
            if arg.startswith("-") or arg in {"(", "!"}:
                break
            starts.append(arg)
        if not starts or any(_resolve(root, s) == root or not _inside(root, s) for s in starts):
            raise Blocked("find -delete must start from a named subdirectory, not the workspace root or outside it")


def _git(args: list[str]) -> None:
    if any(a in {"-c", "-C", "--exec-path", "--git-dir", "--work-tree"} or a.startswith(("--git-dir=", "--work-tree=", "--exec-path=")) for a in args[:3]):
        raise Blocked("git global options are not allowed here")
    sub = next((a for a in args if not a.startswith("-")), "")
    if sub not in READ_ONLY_GIT:
        raise Blocked(f"git {sub or '(no subcommand)'} changes history or state; commits and branches are made by a person. Read-only commands: {', '.join(sorted(READ_ONLY_GIT))}")


def _writes(root: str, prog: str, args: list[str]) -> None:
    in_place = prog in {"sed", "perl"} and any(a.startswith("-") and not a.startswith("--") and "i" in a for a in args)
    if prog in WRITERS or in_place:
        for arg in (a for a in args if not a.startswith("-") and not (prog == "chmod" and MODE.match(a))):
            if prog in {"sed", "perl"} and not _path_like(arg):
                continue  # the expression or a bare file name in the working directory
            if not _target_ok(root, arg):
                raise Blocked(f"{prog}: {arg!r} is outside the workspace or uses a variable where the directory should be literal; writes go to the workspace or /tmp only")


KEYWORDS = {"do", "then", "else", "elif", "if", "while", "until", "!", "{", "}", "done", "fi", "esac", "function"}


def _segment(root: str, words: list[str]) -> None:
    while words and (ASSIGNMENT.match(words[0]) or words[0] in KEYWORDS):  # `do rm -rf /`, `then curl x`: the command behind the keyword is still a command
        words = words[1:]
    while words and posixpath.basename(words[0]) in WRAPPERS:
        wrapper = posixpath.basename(words[0])
        words = words[1:]
        if wrapper == "timeout" and words and re.match(r"^[0-9.]+[smhd]?$", words[0]):
            words = words[1:]
        while words and (words[0].startswith("-") or ASSIGNMENT.match(words[0])):
            words = words[1:]
    if not words:
        return
    prog, args = posixpath.basename(words[0]), words[1:]
    for arg in args:
        _check_path_access(arg)
    if prog in NETWORK:
        raise Blocked(f"{prog}: there is no network in the sandbox")
    if prog in PRIVILEGE:
        raise Blocked(f"{prog}: privilege and container tools are not available")
    if prog in DETACH:
        raise Blocked(f"{prog}: background and scheduled processes are not allowed; run the command in the foreground")
    if prog in PROCESS_CONTROL or prog in DISK or prog in OWNERSHIP:
        raise Blocked(f"{prog}: not available in the sandbox")
    if prog in NESTED_SHELLS:
        raise Blocked(f"{prog}: run the command directly; a nested shell or eval would hide it from the filter")
    if prog in PACKAGE_MANAGERS and any(a in PACKAGE_MANAGERS[prog] for a in args):
        raise Blocked(f"{prog}: there is no network to install packages from; the project's dependencies are already installed")
    if prog in ANY_SUBCOMMAND:
        raise Blocked(f"{prog}: there is no network to download from")
    if prog.startswith("python") and "-m" in args and args[args.index("-m") + 1:][:1] in (["pip"], ["pipx"], ["ensurepip"]):
        raise Blocked("python -m pip: there is no network to install packages from")
    if prog == "git":
        _git(args)
    elif prog in REMOVERS:
        _removal(root, args)
    elif prog == "find":
        _find(root, args)
    elif prog in {"cd", "pushd"}:
        if not _inside(root, next((a for a in args if not a.startswith("-")), "~")):
            raise Blocked("cd: stay inside the workspace")
    else:
        _writes(root, prog, args)


def check_shell(command: str, root: str) -> None:
    """Raise ``Blocked`` (with a reason the model can act on) when ``command`` must not run; return ``None`` when it may.
    ``root`` is the workspace as a POSIX path."""
    if not command.strip():
        raise Blocked("the command is empty")
    if len(command) > MAX_COMMAND_CHARS or "\x00" in command:
        raise Blocked(f"the command is too long or malformed (limit {MAX_COMMAND_CHARS} characters)")
    root = posixpath.normpath(root)
    for line in command.splitlines():
        if not line.strip() or line.strip().startswith("#"):
            continue
        lexer = shlex.shlex(line, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        try:
            tokens = list(lexer)
        except ValueError as exc:
            raise Blocked(f"the command could not be parsed ({exc}); check the quotes") from exc
        words: list[str] = []
        target_next = False
        for token in tokens + [";"]:
            if target_next:
                target_next = False
                if not token.isdigit() and token not in OUTPUT_SINKS:
                    _check_path_access(token)
                    if not _target_ok(root, token):
                        raise Blocked(f"redirection to {token!r}: writes go to the workspace or /tmp only (a variable may only be in the file name, not in the directory)")
                continue
            if token in REDIRECTS:
                target_next = True
            elif token in SEPARATORS or set(token) <= set("();&|"):  # also "()" and other runs of punctuation the tokenizer keeps together
                _segment(root, words)
                words = []
            elif DESCRIPTOR.match(token):
                continue  # 2>&1, <&0: descriptor plumbing
            else:
                words.append(token)
        for first, second in re.findall(r"\$\(([^()]*)\)|`([^`]*)`", line):
            inner = first or second
            if inner.strip():
                check_shell(inner, root)
