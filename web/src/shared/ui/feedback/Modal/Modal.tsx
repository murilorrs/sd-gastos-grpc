import React, { createContext, useContext, forwardRef } from 'react';
import { X } from 'lucide-react';
import './Modal.css';

interface ModalContextType {
    onClose?: () => void;
}

const ModalContext = createContext<ModalContextType | null>(null);

export interface ModalProps extends React.HTMLAttributes<HTMLDivElement> {
    isOpen: boolean;
    onClose: () => void;
    size?: 'sm' | 'md' | 'lg' | 'full';
}

export const Modal = forwardRef<HTMLDivElement, ModalProps>(({
    children,
    isOpen,
    onClose,
    size = 'md',
    className = '',
    ...props
}, ref) => {
    if (!isOpen) return null;

    return (
        <ModalContext.Provider value={{ onClose }}>
            <div className="ui-modal-overlay">
                <div 
                    ref={ref}
                    className={`ui-modal-content ui-modal--${size} ${className}`}
                    role="dialog"
                    aria-modal="true"
                    {...props}
                >
                    {children}
                </div>
            </div>
        </ModalContext.Provider>
    );
});
Modal.displayName = 'Modal';

export interface ModalHeaderProps extends React.HTMLAttributes<HTMLDivElement> {
    title?: string;
    showCloseButton?: boolean;
    icon?: React.ReactNode;
}

export const ModalHeader = forwardRef<HTMLDivElement, ModalHeaderProps>(({
    children,
    title,
    icon,
    showCloseButton = true,
    className = '',
    ...props
}, ref) => {
    const context = useContext(ModalContext);

    return (
        <div ref={ref} className={`ui-modal-header ${className}`} {...props}>
            <div className="ui-modal-header-left">
                {icon && <span className="ui-modal-icon">{icon}</span>}
                {title && <h3 className="ui-modal-title">{title}</h3>}
                {children}
            </div>
            {showCloseButton && context?.onClose && (
                <button
                    className="ui-modal-close-btn"
                    onClick={context.onClose}
                    aria-label="Fechar modal"
                >
                    <X size={20} />
                </button>
            )}
        </div>
    );
});
ModalHeader.displayName = 'ModalHeader';

export interface ModalBodyProps extends React.HTMLAttributes<HTMLDivElement> {}

export const ModalBody = forwardRef<HTMLDivElement, ModalBodyProps>(({
    children,
    className = '',
    ...props
}, ref) => {
    return (
        <div ref={ref} className={`ui-modal-body ${className}`} {...props}>
            {children}
        </div>
    );
});
ModalBody.displayName = 'ModalBody';

export interface ModalFooterProps extends React.HTMLAttributes<HTMLDivElement> {}

export const ModalFooter = forwardRef<HTMLDivElement, ModalFooterProps>(({
    children,
    className = '',
    ...props
}, ref) => {
    return (
        <div ref={ref} className={`ui-modal-footer ${className}`} {...props}>
            {children}
        </div>
    );
});
ModalFooter.displayName = 'ModalFooter';
