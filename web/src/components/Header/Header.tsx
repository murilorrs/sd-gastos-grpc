import React from 'react'
import { LogOut, User } from 'lucide-react'
import { brand } from '@/config/brand'
import { useAuth } from '@/shared/context/AuthContext'
import './Header.css'

const Header: React.FC = () => {
    const { username, authenticated, signOut } = useAuth()

    return (
        <header className="app-header">
            <div className="app-logo">
                <span className="app-logo-mark">{brand.logo.primary}</span>
                <span className="app-logo-accent">{brand.logo.accent}</span>
            </div>

            {authenticated && (
                <div className="app-header-right">
                    <span className="app-user">
                        <User size={15} />
                        {username}
                    </span>
                    <button className="app-logout" onClick={signOut} title="Encerrar sessão">
                        <LogOut size={16} />
                        Sair
                    </button>
                </div>
            )}
        </header>
    )
}

export default Header
