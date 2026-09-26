import React, { forwardRef } from 'react';
import './Card.css';

export interface CardProps extends React.HTMLAttributes<HTMLDivElement> {
    noPadding?: boolean;
}

const Card = forwardRef<HTMLDivElement, CardProps>(({
    children,
    className = '',
    noPadding = false,
    ...props
}, ref) => {
    const combinedClasses = [
        'ui-card',
        noPadding ? 'ui-card--no-padding' : '',
        className
    ].filter(Boolean).join(' ');

    return (
        <div ref={ref} className={combinedClasses} {...props}>
            {children}
        </div>
    );
});

Card.displayName = 'Card';

export default Card;
