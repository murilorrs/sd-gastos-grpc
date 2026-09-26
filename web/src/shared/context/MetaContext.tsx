/**
 * As listas fechadas do domínio, buscadas uma vez em GET /meta.
 *
 * Categorias, métodos e períodos moram no Gateway, onde a validação acontece.
 * Buscá-los em vez de repeti-los aqui é o que garante que um select da tela
 * nunca ofereça um valor que o Gateway vai recusar com 400.
 */

import React, { createContext, useContext, useEffect, useState } from 'react'
import * as gateway from '@/shared/services/gateway'

const FALLBACK: gateway.Meta = {
    methods: ['CREDIT', 'DEBIT'],
    categories: ['other'],
    periods: ['this_month', 'all_time'],
    group_by: ['category', 'card', 'method'],
    nlu: { enabled: false, model: '' },
}

const MetaContext = createContext<gateway.Meta>(FALLBACK)

export const MetaProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
    const [meta, setMeta] = useState<gateway.Meta>(FALLBACK)

    useEffect(() => {
        let alive = true
        gateway.meta()
            .then((value) => { if (alive) setMeta(value) })
            .catch(() => { /* 401 já derruba a sessão; aqui o padrão basta */ })
        return () => { alive = false }
    }, [])

    return <MetaContext.Provider value={meta}>{children}</MetaContext.Provider>
}

export const useMeta = () => useContext(MetaContext)
