import React, { forwardRef } from 'react';
import './Select.css';

export interface SelectOption {
    value: string | number;
    label: string;
    disabled?: boolean;
}

export interface SelectProps extends React.SelectHTMLAttributes<HTMLSelectElement> {
    label?: string;
    error?: string;
    helperText?: string;
    options?: SelectOption[];
    fullWidth?: boolean;
    placeholder?: string;
}

const Select = forwardRef<HTMLSelectElement, SelectProps>(({
    label,
    error,
    helperText,
    options = [],
    fullWidth = true,
    placeholder,
    className = '',
    id,
    disabled,
    children,
    ...props
}, ref) => {
    const selectId = id || `select-${Math.random().toString(36).substr(2, 9)}`;
    
    const containerClasses = [
        'ui-select-container',
        fullWidth ? 'ui-select-container--full-width' : '',
        error ? 'ui-select-container--error' : '',
        disabled ? 'ui-select-container--disabled' : '',
        className
    ].filter(Boolean).join(' ');

    return (
        <div className={containerClasses}>
            {label && (
                <label htmlFor={selectId} className="ui-select-label">
                    {label}
                </label>
            )}
            
            <div className="ui-select-wrapper">
                <select
                    ref={ref}
                    id={selectId}
                    className="ui-select"
                    disabled={disabled}
                    aria-invalid={!!error}
                    aria-describedby={error ? `${selectId}-error` : helperText ? `${selectId}-helper` : undefined}
                    {...props}
                >
                    {placeholder && (
                        <option value="" disabled hidden>
                            {placeholder}
                        </option>
                    )}
                    {children ? children : options.map(opt => (
                        <option key={opt.value} value={opt.value} disabled={opt.disabled}>
                            {opt.label}
                        </option>
                    ))}
                </select>
                <span className="ui-select-arrow" aria-hidden="true">
                    <svg viewBox="0 0 20 20" fill="currentColor">
                        <path fillRule="evenodd" d="M5.293 7.293a1 1 0 011.414 0L10 10.586l3.293-3.293a1 1 0 111.414 1.414l-4 4a1 1 0 01-1.414 0l-4-4a1 1 0 010-1.414z" clipRule="evenodd" />
                    </svg>
                </span>
            </div>

            {error && (
                <span id={`${selectId}-error`} className="ui-select-error-message">
                    {error}
                </span>
            )}
            
            {!error && helperText && (
                <span id={`${selectId}-helper`} className="ui-select-helper-text">
                    {helperText}
                </span>
            )}
        </div>
    );
});

Select.displayName = 'Select';

export default Select;
