import React, { forwardRef } from 'react';
import './Spinner.css';

export interface SpinnerProps extends React.HTMLAttributes<HTMLDivElement> {
    size?: 'sm' | 'md' | 'lg';
    color?: 'primary' | 'white' | 'gray';
}

const Spinner = forwardRef<HTMLDivElement, SpinnerProps>(({
    className = '',
    size = 'md',
    color = 'primary',
    ...props
}, ref) => {
    const combinedClasses = [
        'ui-spinner',
        `ui-spinner--${size}`,
        `ui-spinner--${color}`,
        className
    ].filter(Boolean).join(' ');

    return (
        <div ref={ref} className={combinedClasses} role="status" aria-label="Carregando" {...props}>
            <svg
                className="ui-spinner-svg"
                xmlns="http://www.w3.org/2000/svg"
                fill="none"
                viewBox="0 0 24 24"
            >
                <circle
                    className="ui-spinner-track"
                    cx="12"
                    cy="12"
                    r="10"
                    stroke="currentColor"
                    strokeWidth="2.5"
                />
                <circle
                    className="ui-spinner-head"
                    cx="12"
                    cy="12"
                    r="10"
                    stroke="currentColor"
                    strokeWidth="2.5"
                    strokeDasharray="80"
                    strokeDashoffset="55"
                    strokeLinecap="round"
                />
            </svg>
        </div>
    );
});

Spinner.displayName = 'Spinner';

export default Spinner;

