"""Messages the gateway itself shows to people (errors, confirmations), in Vietnamese or English.

The language is the interface language the browser sends in ``X-UI-Lang`` (the gateway's HTTP middleware sets it for the
request); without it the default is Vietnamese. Answers written by the agents are NOT here: they follow the language of the
question. Add a message by adding the same key to BOTH dictionaries (a test checks they match, placeholders included).
"""

from __future__ import annotations

import re
from contextvars import ContextVar, Token

DEFAULT_LANG = "vi"
SUPPORTED_LANGS = ("vi", "en")

_lang: ContextVar[str] = ContextVar("ui_lang", default=DEFAULT_LANG)

VI: dict[str, str] = {
    "auth.missing": "Thiếu thông tin xác thực.",
    "auth.invalid": "Token không hợp lệ hoặc đã hết hạn.",
    "login.bad": "Sai tên đăng nhập hoặc mật khẩu.",
    "login.disabled": "Đăng nhập tích hợp chưa được bật (cần AUTH_MODE=jwt, AUTH_JWT_SECRET và AUTH_USERS).",
    "rate.limited": "Bạn gửi yêu cầu quá nhanh (tối đa {limit} lượt/phút). Vui lòng thử lại sau {seconds} giây.",
    "service.starting": "Dịch vụ đang khởi động. Vui lòng thử lại sau giây lát.",
    "forbidden.approve": "Bạn không có quyền phê duyệt thao tác này.",
    "forbidden.knowledge": "Bạn không có quyền cập nhật knowledge base.",
    "file.too_big": "Tệp vượt giới hạn {mb} MB.",
    "upload.unsupported": "Chỉ hỗ trợ tệp PDF, DOCX, PPTX, TXT hoặc MD.",
    "upload.no_text": "Không đọc được nội dung văn bản của tệp (tệp rỗng, hỏng hoặc là bản scan cần OCR).",
    "upload.no_text_ocr": "Không đọc được nội dung văn bản của tệp (tệp rỗng, hỏng, hoặc bản scan mà OCR không đọc được).",
    "upload.no_chunks": "Tài liệu không có đoạn nào đủ dài để lưu (mỗi đoạn tối thiểu {min} ký tự).",
    "upload.too_many_chunks": "Tài liệu tạo ra {count} đoạn, vượt giới hạn {limit} cho một lần tải lên.",
    "upload.failed": "Không thể cập nhật knowledge base lúc này (lỗi embedding hoặc cơ sở dữ liệu). Hãy thử lại sau.",
    "upload.unchanged": "Tài liệu **{name}** đã có trong knowledge base (danh mục `{category}`) với nội dung y hệt, nên không có gì thay đổi.",
    "upload.done": "Đã {verb} **{name}** vào knowledge base, danh mục `{category}`: **{chunks} đoạn** từ {sections} mục.",
    "upload.verb_added": "thêm mới",
    "upload.verb_updated": "cập nhật (thay phiên bản cũ)",
    "upload.merged": "- {n} mục ngắn dưới 200 ký tự đã được gộp với mục kế tiếp.",
    "upload.split": "- {n} mục dài hơn 600 ký tự đã được chia thành nhiều đoạn (không mất nội dung).",
    "upload.dupes": "- {n} đoạn trùng gần như hoàn toàn trong cùng tài liệu đã bị bỏ.",
    "upload.replaced": "- {n} đoạn của phiên bản trước đã được thay thế.",
    "upload.ocr": "- Tệp là bản scan: văn bản được đọc bằng OCR nên có thể sai dấu hoặc sai số, hãy kiểm tra các con số quan trọng.",
    "upload.no_copy": "- Không lưu được bản sao vào thư mục dataset: lần chạy `run_ingestion --prune` hoặc `--reset` sau này sẽ xoá tài liệu này.",
    "upload.ask_now": "Bạn có thể hỏi về nội dung tài liệu ngay bây giờ.",
    "kb.not_found": "Không tìm thấy tài liệu này trong knowledge base.",
    "kb.bad_key": "Mã tài liệu không hợp lệ.",
    "kb.page_unavailable": "Không có bản PDF gốc của tài liệu này để xem trang.",
    "conv.not_found": "Không tìm thấy cuộc trò chuyện.",
    "conv.bad_id": "Mã cuộc trò chuyện không hợp lệ.",
    "conv.too_big": "Cuộc trò chuyện vượt giới hạn {mb} MB.",
    "conv.too_many": "Tối đa {limit} cuộc trò chuyện: hãy xoá bớt.",
    "security.injection": "Cảnh báo bảo mật: Phát hiện dấu hiệu Prompt Injection ({label}). Yêu cầu bị từ chối.",
    "csv.too_big": "Tệp '{name}' vượt giới hạn {mb} MB.",
    "csv.unreadable": "Không đọc được tệp '{name}': {reason}",
    "csv.failed": "Phân tích dữ liệu CSV thất bại. Vui lòng kiểm tra định dạng file và thử lại.",
    "analyze.no_active": "Không có dữ liệu đang hoạt động cho phiên này. Hãy tải lại tệp.",
    "filter.invalid": "Bộ lọc không hợp lệ: {reason}",
    "approval.unknown": "Yêu cầu phê duyệt không tồn tại.",
    "orch.invalid_decision": "Quyết định '{decision}' không hợp lệ (chỉ chấp nhận 'approve' hoặc 'reject').",
    "orch.approval_missing": "Yêu cầu phê duyệt '{action_id}' không tồn tại hoặc đã được xử lý.",
    "orch.rejected_by_admin": "Tác vụ [{action_id}] đã bị từ chối thực thi bởi quản trị viên. Lý do: {reason}",
    "orch.cancelled_request": "Người dùng đã hủy yêu cầu.",
    "orch.cancelled_command": "Người dùng đã hủy lệnh.",
    "orch.agent_missing": "Agent '{agent}' không tồn tại trong hệ thống.",
    "orch.api_done": "**Đã phê duyệt & thực thi thành công API ({method} {url}):**\n\n- **Status Code:** HTTP {status}\n- **Kết quả:**\n```json\n{data}\n```",
    "orch.sql_done": "**Đã phê duyệt & thực thi thành công truy vấn SQL:**\n\n- **SQL:** `{sql}`\n- **Số dòng trả về:** {rows}\n- **Dữ liệu:**\n```json\n{data}\n```",
    "orch.exec_failed": "Lỗi khi thực thi tác vụ sau khi phê duyệt: {error}",
    "orch.pev_error": "Đã xảy ra lỗi trong quá trình thực thi hệ thống PEV. Vui lòng thử lại sau.",
    "orch.api_rejected": "Tác vụ gọi API đã bị từ chối bởi người dùng: {reason}",
    "orch.sql_rejected": "Truy vấn SQL đã bị từ chối bởi người dùng: {reason}",
    "orch.api_desc": "Thực hiện gọi REST API {method} tới {url}",
    "orch.sql_desc": "Truy vấn dữ liệu tài chính/bảng lương/nhân sự nhạy cảm",
    "orch.api_needs_approval": "Tác vụ gọi API này làm thay đổi dữ liệu và yêu cầu sự phê duyệt từ quản trị viên trước khi thực thi.",
    "orch.sql_needs_approval": "Truy vấn SQL này chạm vào bảng hoặc dữ liệu nhạy cảm (bảng lương/tài chính/nhân sự) và yêu cầu sự phê duyệt của người dùng trước khi thực thi.",
    "orch.exec_summary": "Thực thi thành công trên Agent [{agent}].",
    "orch.verify_ok": "Kiểm duyệt thành công: Kết quả hợp lệ 100%.",
}

EN: dict[str, str] = {
    "auth.missing": "Authentication is required.",
    "auth.invalid": "The token is invalid or has expired.",
    "login.bad": "Wrong username or password.",
    "login.disabled": "Built-in sign-in is not enabled (needs AUTH_MODE=jwt, AUTH_JWT_SECRET and AUTH_USERS).",
    "rate.limited": "You are sending requests too fast (at most {limit} per minute). Please try again in {seconds} seconds.",
    "service.starting": "The service is starting up. Please try again shortly.",
    "forbidden.approve": "You are not allowed to approve this action.",
    "forbidden.knowledge": "You are not allowed to update the knowledge base.",
    "file.too_big": "The file exceeds the {mb} MB limit.",
    "upload.unsupported": "Only PDF, DOCX, PPTX, TXT or MD files are supported.",
    "upload.no_text": "Could not read any text from the file (it is empty, damaged, or a scan that needs OCR).",
    "upload.no_text_ocr": "Could not read any text from the file (it is empty, damaged, or a scan that OCR could not read).",
    "upload.no_chunks": "The document has no passage long enough to store (each passage needs at least {min} characters).",
    "upload.too_many_chunks": "The document produces {count} passages, over the limit of {limit} per upload.",
    "upload.failed": "The knowledge base cannot be updated right now (embedding or database error). Please try again later.",
    "upload.unchanged": "**{name}** is already in the knowledge base (category `{category}`) with identical content, so nothing changed.",
    "upload.done": "{verb} **{name}** in the knowledge base, category `{category}`: **{chunks} passages** from {sections} sections.",
    "upload.verb_added": "Added",
    "upload.verb_updated": "Updated (replaced the old version)",
    "upload.merged": "- {n} sections shorter than 200 characters were merged with the next one.",
    "upload.split": "- {n} sections longer than 600 characters were split into several passages (nothing was lost).",
    "upload.dupes": "- {n} near-identical passages within the same document were dropped.",
    "upload.replaced": "- {n} passages of the previous version were replaced.",
    "upload.ocr": "- The file is a scan: its text was read by OCR, so accents or numbers may be wrong. Check the figures that matter.",
    "upload.no_copy": "- A copy could not be kept in the dataset folder: a later `run_ingestion --prune` or `--reset` will remove this document.",
    "upload.ask_now": "You can ask about the document now.",
    "kb.not_found": "This document is not in the knowledge base.",
    "kb.bad_key": "Invalid document key.",
    "kb.page_unavailable": "The original PDF of this document is not available for page preview.",
    "conv.not_found": "Conversation not found.",
    "conv.bad_id": "Invalid conversation id.",
    "conv.too_big": "The conversation exceeds the {mb} MB limit.",
    "conv.too_many": "At most {limit} conversations: please delete some.",
    "security.injection": "Security warning: signs of prompt injection detected ({label}). The request was refused.",
    "csv.too_big": "The file '{name}' exceeds the {mb} MB limit.",
    "csv.unreadable": "Could not read the file '{name}': {reason}",
    "csv.failed": "The CSV analysis failed. Please check the file format and try again.",
    "analyze.no_active": "There is no active dataset for this session. Please upload the file again.",
    "filter.invalid": "Invalid filter: {reason}",
    "approval.unknown": "The approval request does not exist.",
    "orch.invalid_decision": "The decision '{decision}' is not valid (only 'approve' or 'reject').",
    "orch.approval_missing": "The approval request '{action_id}' does not exist or was already handled.",
    "orch.rejected_by_admin": "The action [{action_id}] was rejected by the administrator. Reason: {reason}",
    "orch.cancelled_request": "The user cancelled the request.",
    "orch.cancelled_command": "The user cancelled the command.",
    "orch.agent_missing": "The agent '{agent}' does not exist in the system.",
    "orch.api_done": "**Approved and executed the API call ({method} {url}):**\n\n- **Status Code:** HTTP {status}\n- **Result:**\n```json\n{data}\n```",
    "orch.sql_done": "**Approved and executed the SQL query:**\n\n- **SQL:** `{sql}`\n- **Rows returned:** {rows}\n- **Data:**\n```json\n{data}\n```",
    "orch.exec_failed": "Could not run the action after approval: {error}",
    "orch.pev_error": "An error occurred while the PEV system was running. Please try again later.",
    "orch.api_rejected": "The API call was rejected by the user: {reason}",
    "orch.sql_rejected": "The SQL query was rejected by the user: {reason}",
    "orch.api_desc": "Call the REST API {method} on {url}",
    "orch.sql_desc": "Query sensitive financial, payroll or HR data",
    "orch.api_needs_approval": "This API call changes data and needs the administrator's approval before it runs.",
    "orch.sql_needs_approval": "This SQL query touches sensitive tables or data (payroll, finance, HR) and needs the user's approval before it runs.",
    "orch.exec_summary": "Executed successfully on Agent [{agent}].",
    "orch.verify_ok": "Audit passed: the result is 100% valid.",
}

CATALOGS: dict[str, dict[str, str]] = {"vi": VI, "en": EN}


def pick_lang(header: str | None) -> str:
    """``vi`` / ``en`` from an ``X-UI-Lang`` or ``Accept-Language`` style value; anything else -> the default."""
    match = re.match(r"\s*([a-zA-Z]{2})", header or "")
    code = match.group(1).lower() if match else ""
    return code if code in SUPPORTED_LANGS else DEFAULT_LANG


def set_lang(lang: str) -> Token:
    return _lang.set(lang if lang in SUPPORTED_LANGS else DEFAULT_LANG)


def reset_lang(token: Token) -> None:
    _lang.reset(token)


def current_lang() -> str:
    return _lang.get()


def msg(key: str, **values: object) -> str:
    """The message ``key`` in the request's language, placeholders filled in."""
    template = CATALOGS[_lang.get()][key]
    return template.format(**values) if values else template
