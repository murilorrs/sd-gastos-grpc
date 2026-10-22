import React, { forwardRef } from 'react';
import { CheckCircle, XCircle, AlertTriangle, Info } from 'lucide-react';
import './Alert.css';

export interface AlertProps extends React.HTMLAttributes<HTMLDivElement> {
    variant?: 'success' | 'error' | 'warning' | 'info';
    title?: string;
    showIcon?: boolean;
}

const ICONS = {
    success: <CheckCircle size={20} />,
    error: <XCircle size={20} />,
    warning: <AlertTriangle size={20} />,
    info: <Info size={20} />
};

const Alert = forwardRef<HTMLDivElement, AlertProps>(({
    children,
    className = '',
    variant = 'info',
    title,
    showIcon = true,
    ...props
}, ref) => {
    const combinedClasses = [
        'ui-alert',
        `ui-alert--${variant}`,
        className
    ].filter(Boolean).join(' ');

    return (
        <div ref={ref} className={combinedClasses} role="alert" {...props}>
            {showIcon && (
                <div className="ui-alert__icon">
                    {ICONS[variant]}
                </div>
            )}
            <div className="ui-alert__content">
                {title && <h5 className="ui-alert__title">{title}</h5>}
                <div className="ui-alert__body">
                    {children}
                </div>
            </div>
        </div>
    );
});

Alert.displayName = 'Alert';

export default Alert;
