import React from 'react';
import './Badge.css';

export interface BadgeProps {
    children: React.ReactNode;
    variant?: 'primary' | 'secondary' | 'success' | 'danger' | 'warning' | 'info' | 'gray';
    styleType?: 'solid' | 'subtle' | 'outline';
    isRound?: boolean;
    className?: string;
}

const Badge: React.FC<BadgeProps> = ({
    children,
    variant = 'gray',
    styleType = 'subtle',
    isRound = false,
    className = '',
}) => {
    const combinedClasses = [
        'ui-badge',
        `ui-badge--${variant}`,
        `ui-badge--${styleType}`,
        isRound ? 'ui-badge--round' : '',
        className
    ].filter(Boolean).join(' ');

    return (
        <span className={combinedClasses}>
            {children}
        </span>
    );
};

export default Badge;
