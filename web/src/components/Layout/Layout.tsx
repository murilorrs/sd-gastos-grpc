import React from 'react'
import { Outlet } from 'react-router-dom'
import Header from '@/components/Header/Header'
import Sidebar from '@/components/Sidebar/Sidebar'

/** Cabeçalho fixo, navegação à esquerda, página à direita. */
const Layout: React.FC = () => (
    <div className="layout">
        <Header />
        <div className="layout-body">
            <Sidebar />
            <main className="layout-main">
                <Outlet />
            </main>
        </div>
    </div>
)

export default Layout
