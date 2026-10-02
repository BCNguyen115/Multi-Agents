export type ToastType = 'success' | 'error' | 'info' | 'warning';

export interface ToastItem {
  id: string;
  type: ToastType;
  title?: string;
  message: string;
  duration?: number;
  action?: {
    label: string;
    onClick: () => void;
  };
}

type ToastListener = (toasts: ToastItem[]) => void;

class ToastManager {
  private toasts: ToastItem[] = [];
  private listeners: Set<ToastListener> = new Set();

  public subscribe(listener: ToastListener): () => void {
    this.listeners.add(listener);
    listener([...this.toasts]);
    return () => {
      this.listeners.delete(listener);
    };
  }

  private notify() {
    const copy = [...this.toasts];
    this.listeners.forEach((listener) => listener(copy));
  }

  public show(item: Omit<ToastItem, 'id'>): string {
    const id = `toast-${Date.now()}-${Math.random().toString(36).substr(2, 6)}`;
    const toast: ToastItem = {
      ...item,
      id,
      duration: item.duration ?? 3500,
    };

    this.toasts = [...this.toasts, toast];
    this.notify();

    if (toast.duration && toast.duration > 0) {
      setTimeout(() => {
        this.dismiss(id);
      }, toast.duration);
    }

    return id;
  }

  public dismiss(id: string) {
    this.toasts = this.toasts.filter((t) => t.id !== id);
    this.notify();
  }

  public success(message: string, options?: { title?: string; duration?: number; action?: { label: string; onClick: () => void } }) {
    return this.show({ type: 'success', message, ...options });
  }

  public error(message: string, options?: { title?: string; duration?: number; action?: { label: string; onClick: () => void } }) {
    return this.show({ type: 'error', message, ...options });
  }

  public info(message: string, options?: { title?: string; duration?: number; action?: { label: string; onClick: () => void } }) {
    return this.show({ type: 'info', message, ...options });
  }

  public warning(message: string, options?: { title?: string; duration?: number; action?: { label: string; onClick: () => void } }) {
    return this.show({ type: 'warning', message, ...options });
  }
}

export const toast = new ToastManager();
