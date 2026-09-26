import React from 'react';
import { TrendingUp, TrendingDown } from 'lucide-react';
import './StatCard.css';

export interface StatCardProps {
    label: string;
    value: string | number;
    icon?: React.ReactNode;
    trend?: {
        value: string | number;
        direction: 'up' | 'down';
    };
    description?: string;
    variant?: 'primary' | 'success' | 'danger' | 'warning' | 'info' | 'gray';
    className?: string;
}

const StatCard: React.FC<StatCardProps> = ({
    label,
    value,
    icon,
    trend,
    description,
    variant = 'primary',
    className = '',
}) => {
    return (
        <div className={`ui-stat-card ui-stat-card--${variant} ${className}`}>
            <div className="ui-stat-card-header">
                <span className="ui-stat-card-label">{label}</span>
                {icon && <div className="ui-stat-card-icon">{icon}</div>}
            </div>
            
            <div className="ui-stat-card-body">
                <div className="ui-stat-card-value">{value}</div>
                {trend && (
                    <div className={`ui-stat-card-trend is-${trend.direction}`}>
                        {trend.direction === 'up' ? <TrendingUp size={14} /> : <TrendingDown size={14} />}
                        <span>{trend.value}</span>
                    </div>
                )}
            </div>

            {description && <div className="ui-stat-card-footer">{description}</div>}
        </div>
    );
};

export default StatCard;
