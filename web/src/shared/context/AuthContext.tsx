/**
 * A sessão: o JWT emitido pelo Gateway e o usuário dono dele.
 *
 * O token fica no sessionStorage — some quando a aba fecha, e não é enviado
 * por cookie, então não há CSRF a tratar. Ele vale uma hora; quando vence,
 * qualquer chamada devolve 401, a camada de API dispara UNAUTHORIZED_EVENT e
 * a sessão termina aqui, devolvendo o usuário para a tela de login.
 */

import React, { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { getToken, setToken, UNAUTHORIZED_EVENT } from '@/shared/services/api'
import * as gateway from '@/shared/services/gateway'

interface AuthState {
    username: string | null
    authenticated: boolean
    signIn: (username: string, password: string) => Promise<void>
    signOut: () => void
    expiredMessage: string | null
    clearExpiredMessage: () => void
}

const USER_KEY = 'grana:user'

const AuthContext = createContext<AuthState | null>(null)

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
    const [username, setUsername] = useState<string | null>(
        () => (getToken() ? sessionStorage.getItem(USER_KEY) : null),
    )
    const [expiredMessage, setExpiredMessage] = useState<string | null>(null)

    const signIn = useCallback(async (user: string, password: string) => {
        const token = await gateway.login(user, password)
        setToken(token.access_token)
        sessionStorage.setItem(USER_KEY, user)
        setUsername(user)
        setExpiredMessage(null)
    }, [])

    const signOut = useCallback(() => {
        setToken(null)
        sessionStorage.removeItem(USER_KEY)
        setUsername(null)
    }, [])

    useEffect(() => {
        const onUnauthorized = () => {
            sessionStorage.removeItem(USER_KEY)
            setUsername(null)
            setExpiredMessage('Sua sessão expirou. Entre novamente.')
        }
        window.addEventListener(UNAUTHORIZED_EVENT, onUnauthorized)
        return () => window.removeEventListener(UNAUTHORIZED_EVENT, onUnauthorized)
    }, [])

    const value = useMemo<AuthState>(() => ({
        username,
        authenticated: Boolean(username && getToken()),
        signIn,
        signOut,
        expiredMessage,
        clearExpiredMessage: () => setExpiredMessage(null),
    }), [username, signIn, signOut, expiredMessage])

    return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthState {
    const context = useContext(AuthContext)
    if (!context) throw new Error('useAuth precisa estar dentro de <AuthProvider>')
    return context
}
