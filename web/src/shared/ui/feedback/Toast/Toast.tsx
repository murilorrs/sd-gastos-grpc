import React, { useEffect, useRef } from 'react'
import { CheckCircle, XCircle, AlertTriangle, Info, X } from 'lucide-react'
import { ToastMessage, ToastType } from '@/shared/hooks/useToast'
import './Toast.css'

interface ToastItemProps {
    toast: ToastMessage
    onDismiss: (id: string) => void
    duration?: number
}

const ICONS: Record<ToastType, React.ReactNode> = {
    success: <CheckCircle size={20} />,
    error: <XCircle size={20} />,
    warning: <AlertTriangle size={20} />,
    info: <Info size={20} />,
}

const ToastItem: React.FC<ToastItemProps> = ({ toast, onDismiss, duration = 4000 }) => {
    const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

    useEffect(() => {
        timerRef.current = setTimeout(() => onDismiss(toast.id), duration)
        return () => {
            if (timerRef.current) clearTimeout(timerRef.current)
        }
    }, [toast.id, onDismiss, duration])

    return (
        <div className={`toast toast--${toast.type}`} role="alert" aria-live="assertive">
            <span className="toast__icon">{ICONS[toast.type]}</span>
            <div className="toast__body">
                {toast.title && <p className="toast__title">{toast.title}</p>}
                <p className="toast__message">{toast.message}</p>
            </div>
            <button
                className="toast__close"
                onClick={() => onDismiss(toast.id)}
                aria-label="Fechar"
            >
                <X size={16} />
            </button>
        </div>
    )
}

interface ToastContainerProps {
    toasts: ToastMessage[]
    onDismiss: (id: string) => void
    duration?: number
}

const ToastContainer: React.FC<ToastContainerProps> = ({ toasts, onDismiss, duration }) => {
    if (toasts.length === 0) return null
    return (
        <div className="toast-container" aria-label="Notificações">
            {toasts.map(toast => (
                <ToastItem
                    key={toast.id}
                    toast={toast}
                    onDismiss={onDismiss}
                    duration={duration}
                />
            ))}
        </div>
    )
}

export default ToastContainer
