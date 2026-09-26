import React, { useState } from 'react'
import { Eye, EyeOff, LockKeyhole } from 'lucide-react'
import { brand } from '@/config/brand'
import { useAuth } from '@/shared/context/AuthContext'
import { ApiError } from '@/shared/services/api'
import { Button, Input } from '@/shared/ui/forms'
import { Alert } from '@/shared/ui/feedback'
import './LoginPage.css'

/**
 * A porta de entrada. Troca usuário e senha por um JWT em POST /auth/token —
 * a única rota que não exige token. Daí em diante toda chamada leva o
 * cabeçalho Authorization, e quem não levar leva 401 antes de qualquer
 * processamento.
 */
const LoginPage: React.FC = () => {
    const { signIn, expiredMessage, clearExpiredMessage } = useAuth()
    const [username, setUsername] = useState('')
    const [password, setPassword] = useState('')
    const [showPassword, setShowPassword] = useState(false)
    const [error, setError] = useState<string | null>(null)
    const [loading, setLoading] = useState(false)

    const submit = async (event: React.FormEvent) => {
        event.preventDefault()
        clearExpiredMessage()
        if (!username.trim() || !password) {
            setError('Preencha usuário e senha.')
            return
        }

        setLoading(true)
        setError(null)
        try {
            await signIn(username.trim(), password)
        } catch (failure) {
            if (failure instanceof ApiError && failure.status === 401) {
                setError('Usuário ou senha inválidos.')
            } else if (failure instanceof ApiError && failure.status === 0) {
                setError('Não foi possível conectar. Verifique sua conexão e tente de novo.')
            } else {
                setError(failure instanceof Error ? failure.message : 'Falha no login.')
            }
        } finally {
            setLoading(false)
        }
    }

    return (
        <div className="login">
            <aside className="login-side">
                <div className="login-brand">
                    <span className="login-brand-mark">{brand.logo.primary}</span>
                    <span className="login-brand-accent">{brand.logo.accent}</span>
                </div>
                <h2>Cada gasto no seu cartão.</h2>
                <p>
                    Lance, filtre e acompanhe por categoria, cartão e período.
                </p>
            </aside>

            <main className="login-main">
                <form className="login-form" onSubmit={submit}>
                    <div className="login-form-head">
                        <LockKeyhole size={20} />
                        <h1>Entrar</h1>
                    </div>

                    {expiredMessage && <Alert variant="warning">{expiredMessage}</Alert>}
                    {error && <Alert variant="error">{error}</Alert>}

                    <Input
                        label="Usuário"
                        placeholder="seu usuário"
                        autoComplete="username"
                        value={username}
                        onChange={(event) => setUsername(event.target.value)}
                        disabled={loading}
                    />

                    <Input
                        label="Senha"
                        type={showPassword ? 'text' : 'password'}
                        placeholder="••••••••"
                        autoComplete="current-password"
                        value={password}
                        onChange={(event) => setPassword(event.target.value)}
                        disabled={loading}
                        icon={
                            <span
                                className="login-eye"
                                role="button"
                                tabIndex={0}
                                aria-label={showPassword ? 'Ocultar senha' : 'Mostrar senha'}
                                onClick={() => setShowPassword(!showPassword)}
                                onKeyDown={(event) => event.key === 'Enter' && setShowPassword(!showPassword)}
                            >
                                {showPassword ? <EyeOff size={17} /> : <Eye size={17} />}
                            </span>
                        }
                        iconPosition="right"
                    />

                    <Button type="submit" fullWidth size="lg" isLoading={loading}>
                        Entrar
                    </Button>
                </form>
            </main>
        </div>
    )
}

export default LoginPage
