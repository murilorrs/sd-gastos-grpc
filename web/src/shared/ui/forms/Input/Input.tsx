import React, { forwardRef } from 'react';
import './Input.css';

export interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {
    label?: string;
    error?: string;
    helperText?: string;
    icon?: React.ReactNode;
    iconPosition?: 'left' | 'right';
    fullWidth?: boolean;
}

const Input = forwardRef<HTMLInputElement, InputProps>(({
    label,
    error,
    helperText,
    icon,
    iconPosition = 'left',
    fullWidth = true,
    className = '',
    id,
    disabled,
    ...props
}, ref) => {
    const inputId = id || `input-${Math.random().toString(36).substr(2, 9)}`;
    
    const containerClasses = [
        'ui-input-container',
        fullWidth ? 'ui-input-container--full-width' : '',
        error ? 'ui-input-container--error' : '',
        disabled ? 'ui-input-container--disabled' : '',
        className
    ].filter(Boolean).join(' ');

    const wrapperClasses = [
        'ui-input-wrapper',
        icon ? `ui-input-wrapper--has-icon ui-input-wrapper--icon-${iconPosition}` : ''
    ].filter(Boolean).join(' ');

    return (
        <div className={containerClasses}>
            {label && (
                <label htmlFor={inputId} className="ui-input-label">
                    {label}
                </label>
            )}
            
            <div className={wrapperClasses}>
                {icon && <span className="ui-input-icon">{icon}</span>}
                <input
                    ref={ref}
                    id={inputId}
                    className="ui-input"
                    disabled={disabled}
                    aria-invalid={!!error}
                    aria-describedby={error ? `${inputId}-error` : helperText ? `${inputId}-helper` : undefined}
                    {...props}
                />
            </div>

            {error && (
                <span id={`${inputId}-error`} className="ui-input-error-message">
                    {error}
                </span>
            )}
            
            {!error && helperText && (
                <span id={`${inputId}-helper`} className="ui-input-helper-text">
                    {helperText}
                </span>
            )}
        </div>
    );
});

Input.displayName = 'Input';

export default Input;
