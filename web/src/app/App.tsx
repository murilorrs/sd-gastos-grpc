import React from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import Layout from '@/components/Layout/Layout'
import { useAuth } from '@/shared/context/AuthContext'
import { MetaProvider } from '@/shared/context/MetaContext'
import LoginPage from '@/features/auth/LoginPage'
import DashboardPage from '@/features/dashboard/DashboardPage'
import ExpensesPage from '@/features/expenses/ExpensesPage'
import CardsPage from '@/features/cards/CardsPage'
import AssistantPage from '@/features/assistant/AssistantPage'
import DiagnosticsPage from '@/features/diagnostics/DiagnosticsPage'

/**
 * Sem sessão, só existe a tela de login — as rotas de dentro nem são montadas.
 * Não é segurança (a de verdade é o 401 do servidor, que independe do que o
 * navegador acha); é só não desenhar uma tela que não teria dados para
 * preencher.
 */
const App: React.FC = () => {
    const { authenticated } = useAuth()

    if (!authenticated) {
        return (
            <Routes>
                <Route path="*" element={<LoginPage />} />
            </Routes>
        )
    }

    return (
        <MetaProvider>
            <Routes>
                <Route element={<Layout />}>
                    <Route index element={<DashboardPage />} />
                    <Route path="gastos" element={<ExpensesPage />} />
                    <Route path="cartoes" element={<CardsPage />} />
                    <Route path="assistente" element={<AssistantPage />} />
                    <Route path="diagnostico" element={<DiagnosticsPage />} />
                    <Route path="*" element={<Navigate to="/" replace />} />
                </Route>
            </Routes>
        </MetaProvider>
    )
}

export default App
