import React, { forwardRef } from 'react';
import Button, { ButtonProps } from '../Button/Button';
import './IconButton.css';

export interface IconButtonProps extends Omit<ButtonProps, 'iconLeft' | 'iconRight' | 'fullWidth'> {
    icon: React.ReactNode;
    isRound?: boolean;
}

const IconButton = forwardRef<HTMLButtonElement, IconButtonProps>(({
    icon,
    isRound = false,
    className = '',
    children,
    ...props
}, ref) => {
    const combinedClasses = [
        'ui-icon-button',
        isRound ? 'ui-icon-button--round' : '',
        className
    ].filter(Boolean).join(' ');

    return (
        <Button
            ref={ref}
            className={combinedClasses}
            {...props}
        >
            <span className="ui-icon-button__icon">{icon}</span>
            {children && <span className="ui-sr-only">{children}</span>}
        </Button>
    );
});

IconButton.displayName = 'IconButton';

export default IconButton;
