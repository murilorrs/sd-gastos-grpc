import React from 'react';
import { ChevronUp, ChevronDown } from 'lucide-react';
import './Table.css';

export interface TableProps {
    children: React.ReactNode;
    fullWidth?: boolean;
    className?: string;
}

const Table: React.FC<TableProps> = ({ children, fullWidth = true, className = '' }) => (
    <div className={`ui-table-container ${fullWidth ? 'ui-table--full-width' : ''}`}>
        <table className={`ui-table ${className}`}>{children}</table>
    </div>
);

export const Thead: React.FC<{ children: React.ReactNode }> = ({ children }) => (
    <thead className="ui-table-thead">{children}</thead>
);

export const Tbody: React.FC<{ children: React.ReactNode }> = ({ children }) => (
    <tbody className="ui-table-tbody">{children}</tbody>
);

export const Tr: React.FC<{ children: React.ReactNode; className?: string; onClick?: () => void }> = ({ children, className = '', onClick }) => (
    <tr className={`ui-table-tr ${onClick ? 'is-clickable' : ''} ${className}`} onClick={onClick}>{children}</tr>
);

export const Th: React.FC<{ children?: React.ReactNode; className?: string; align?: 'left' | 'center' | 'right' }> = ({ children, className = '', align = 'left' }) => (
    <th className={`ui-table-th ui-table--align-${align} ${className}`}>{children}</th>
);

export const Td: React.FC<{ children?: React.ReactNode; className?: string; align?: 'left' | 'center' | 'right' }> = ({ children, className = '', align = 'left' }) => (
    <td className={`ui-table-td ui-table--align-${align} ${className}`}>{children}</td>
);

export interface SortableHeaderProps {
    label: string;
    sortKey: string;
    currentSort?: { key: string; direction: 'asc' | 'desc' };
    onSort?: (key: string) => void;
    align?: 'left' | 'center' | 'right';
}

export const SortableHeader: React.FC<SortableHeaderProps> = ({ 
    label, 
    sortKey, 
    currentSort, 
    onSort,
    align = 'left'
}) => {
    const isActive = currentSort?.key === sortKey;
    
    return (
        <Th align={align} className="ui-table-th--sortable">
            <button className="ui-table-sort-btn" onClick={() => onSort?.(sortKey)}>
                <span>{label}</span>
                <span className="ui-table-sort-icons">
                    <ChevronUp className={`ui-sort-icon ${isActive && currentSort?.direction === 'asc' ? 'is-active' : ''}`} size={12} />
                    <ChevronDown className={`ui-sort-icon ${isActive && currentSort?.direction === 'desc' ? 'is-active' : ''}`} size={12} />
                </span>
            </button>
        </Th>
    );
};

export default Table;
