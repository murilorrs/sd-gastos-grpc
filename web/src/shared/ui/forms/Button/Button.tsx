import React, { forwardRef } from 'react';
import './Button.css';

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
    variant?: 'primary' | 'secondary' | 'danger' | 'success' | 'ghost' | 'outline';
    size?: 'sm' | 'md' | 'lg';
    isLoading?: boolean;
    iconLeft?: React.ReactNode;
    iconRight?: React.ReactNode;
    fullWidth?: boolean;
}

const Button = forwardRef<HTMLButtonElement, ButtonProps>(({
    children,
    variant = 'primary',
    size = 'md',
    isLoading = false,
    iconLeft,
    iconRight,
    fullWidth = false,
    className = '',
    disabled,
    ...props
}, ref) => {
    const baseClass = 'ui-button';
    const variantClass = `${baseClass}--${variant}`;
    const sizeClass = `${baseClass}--${size}`;
    const loadingClass = isLoading ? 'is-loading' : '';
    const fullWidthClass = fullWidth ? `${baseClass}--full-width` : '';
    
    const combinedClasses = [
        baseClass,
        variantClass,
        sizeClass,
        loadingClass,
        fullWidthClass,
        className
    ].filter(Boolean).join(' ');

    return (
        <button
            ref={ref}
            className={combinedClasses}
            disabled={disabled || isLoading}
            aria-busy={isLoading}
            {...props}
        >
            {isLoading && (
                <svg className="ui-button__spinner" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                </svg>
            )}
            
            {!isLoading && iconLeft && <span className="ui-button__icon-left">{iconLeft}</span>}
            <span className="ui-button__text">{children}</span>
            {!isLoading && iconRight && <span className="ui-button__icon-right">{iconRight}</span>}
        </button>
    );
});

Button.displayName = 'Button';

export default Button;
