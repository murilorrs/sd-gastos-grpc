import { useState, useCallback } from 'react'

export type ToastType = 'success' | 'error' | 'warning' | 'info'

export interface ToastMessage {
    id: string
    type: ToastType
    title?: string
    message: string
}

export function useToast() {
    const [toasts, setToasts] = useState<ToastMessage[]>([])

    const show = useCallback((message: string, type: ToastType = 'info', title?: string) => {
        const id = crypto.randomUUID()
        setToasts(prev => [...prev, { id, type, title, message }])
        return id
    }, [])

    const dismiss = useCallback((id: string) => {
        setToasts(prev => prev.filter(t => t.id !== id))
    }, [])

    const success = useCallback((message: string, title?: string) => show(message, 'success', title), [show])
    const error = useCallback((message: string, title?: string) => show(message, 'error', title), [show])
    const warning = useCallback((message: string, title?: string) => show(message, 'warning', title), [show])
    const info = useCallback((message: string, title?: string) => show(message, 'info', title), [show])

    return { toasts, show, dismiss, success, error, warning, info }
}
