import React from 'react';
import './EmptyState.css';

export interface EmptyStateProps {
    icon?: React.ReactNode;
    title: string;
    description?: string;
    action?: React.ReactNode;
    className?: string;
}

const EmptyState: React.FC<EmptyStateProps> = ({
    icon,
    title,
    description,
    action,
    className = '',
}) => {
    return (
        <div className={`ui-empty-state ${className}`}>
            {icon && <div className="ui-empty-state-icon">{icon}</div>}
            <h3 className="ui-empty-state-title">{title}</h3>
            {description && <p className="ui-empty-state-description">{description}</p>}
            {action && <div className="ui-empty-state-action">{action}</div>}
        </div>
    );
};

export default EmptyState;
