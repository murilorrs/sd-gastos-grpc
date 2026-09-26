import React from 'react'
import { NavLink } from 'react-router-dom'
import { Activity, CreditCard, LayoutDashboard, Receipt, Sparkles } from 'lucide-react'
import './Sidebar.css'

interface Item {
    to: string
    label: string
    icon: React.ReactNode
}

const ITEMS: Item[] = [
    { to: '/', label: 'Painel', icon: <LayoutDashboard size={17} /> },
    { to: '/gastos', label: 'Gastos', icon: <Receipt size={17} /> },
    { to: '/cartoes', label: 'Cartões', icon: <CreditCard size={17} /> },
    { to: '/assistente', label: 'Assistente', icon: <Sparkles size={17} /> },
    { to: '/diagnostico', label: 'Diagnóstico', icon: <Activity size={17} /> },
]

const Sidebar: React.FC = () => (
    <nav className="sidebar" aria-label="Navegação principal">
        <ul className="sidebar-list">
            {ITEMS.map((item) => (
                <li key={item.to}>
                    <NavLink
                        to={item.to}
                        end={item.to === '/'}
                        className={({ isActive }) => `sidebar-link${isActive ? ' is-active' : ''}`}
                    >
                        <span className="sidebar-icon">{item.icon}</span>
                        <span className="sidebar-label">{item.label}</span>
                    </NavLink>
                </li>
            ))}
        </ul>
    </nav>
)

export default Sidebar
