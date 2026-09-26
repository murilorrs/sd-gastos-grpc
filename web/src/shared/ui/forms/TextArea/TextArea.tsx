import React, { forwardRef } from 'react';
import './TextArea.css';

export interface TextAreaProps extends React.TextareaHTMLAttributes<HTMLTextAreaElement> {
    label?: string;
    error?: string;
    helperText?: string;
    fullWidth?: boolean;
    resize?: 'none' | 'vertical' | 'horizontal' | 'both';
}

const TextArea = forwardRef<HTMLTextAreaElement, TextAreaProps>(({
    label,
    error,
    helperText,
    fullWidth = true,
    resize = 'vertical',
    className = '',
    id,
    disabled,
    rows = 4,
    ...props
}, ref) => {
    const textAreaId = id || `textarea-${Math.random().toString(36).substr(2, 9)}`;
    
    const containerClasses = [
        'ui-textarea-container',
        fullWidth ? 'ui-textarea-container--full-width' : '',
        error ? 'ui-textarea-container--error' : '',
        disabled ? 'ui-textarea-container--disabled' : '',
        className
    ].filter(Boolean).join(' ');

    const textAreaClasses = [
        'ui-textarea',
        `ui-textarea--resize-${resize}`
    ].filter(Boolean).join(' ');

    return (
        <div className={containerClasses}>
            {label && (
                <label htmlFor={textAreaId} className="ui-textarea-label">
                    {label}
                </label>
            )}
            
            <textarea
                ref={ref}
                id={textAreaId}
                className={textAreaClasses}
                disabled={disabled}
                rows={rows}
                aria-invalid={!!error}
                aria-describedby={error ? `${textAreaId}-error` : helperText ? `${textAreaId}-helper` : undefined}
                {...props}
            />

            {error && (
                <span id={`${textAreaId}-error`} className="ui-textarea-error-message">
                    {error}
                </span>
            )}
            
            {!error && helperText && (
                <span id={`${textAreaId}-helper`} className="ui-textarea-helper-text">
                    {helperText}
                </span>
            )}
        </div>
    );
});

TextArea.displayName = 'TextArea';

export default TextArea;
