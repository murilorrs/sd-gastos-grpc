/**
 * O contrato do Gateway, em TypeScript.
 *
 * Cada função corresponde a uma rota HTTP, e cada rota corresponde a um RPC
 * gRPC do outro lado. As listas fechadas (categorias, métodos, períodos) não
 * são copiadas aqui: vêm de GET /meta, que as publica a partir dos mesmos
 * tipos que o Gateway usa para validar — uma cópia local sairia de sincronia
 * com a validação real na primeira mudança.
 */

import { api } from './api'

export type PaymentMethod = 'CREDIT' | 'DEBIT'

export interface Card {
    name: string
    methods: PaymentMethod[]
}

export interface Expense {
    id: number
    product: string
    description: string
    amount: number
    card: string
    method: PaymentMethod
    category: string
    date: string
    created_at: string
}

export interface ExpenseInput {
    product: string
    description?: string
    amount: number
    card: string
    method: PaymentMethod
    category: string
    date?: string
}

export interface ExpenseFilter {
    card?: string
    method?: string
    category?: string
    start_date?: string
    end_date?: string
}

export interface GroupTotal {
    key: string
    total: number
    count: number
}

export interface Summary {
    totals: GroupTotal[]
    grand_total: number
}

export interface Meta {
    methods: PaymentMethod[]
    categories: string[]
    periods: string[]
    group_by: string[]
    nlu: { enabled: boolean; model: string }
}

export interface Validation {
    exists: boolean
    name: string
    message: string
    suggestions: Card[]
}

/** O que POST /nlu/interpret devolve — ver gateway/app.py. */
export interface Interpretation {
    status: 'ok' | 'needs_card' | 'needs_method' | 'unknown' | 'rejected'
    action: string
    args: Record<string, unknown>
    message?: string
    interpreter: 'claude' | 'offline'
    model: string | null
    fallback_reason: string | null
    elapsed_ms: number
    pending?: Record<string, unknown>
    suggestions?: Card[]
    result?: {
        expense?: Expense
        expenses?: Expense[]
        cards?: unknown[]
        totals?: GroupTotal[]
        grand_total?: number
        group_by?: string
        filter?: Record<string, string | null>
    }
}

// --- autenticação -----------------------------------------------------------

export interface Token {
    access_token: string
    token_type: string
    expires_in: number
}

export const login = (username: string, password: string) =>
    api.post<Token>('/auth/token', { username, password }, { auth: 'none' })

export const meta = () => api.get<Meta>('/meta')

// --- cartões ----------------------------------------------------------------

export const listCards = () => api.get<{ cards: Card[] }>('/cards').then((r) => r.cards)

export const registerCard = (name: string, method: PaymentMethod) =>
    api.post<{ message: string; created: boolean }>('/cards', { name, method })

export const validateCard = (name: string, method?: PaymentMethod) =>
    api.get<Validation>('/cards/validate', { query: { name, method } })

// --- gastos -----------------------------------------------------------------

export const listExpenses = (filter: ExpenseFilter = {}) =>
    api.get<{ expenses: Expense[] }>('/expenses', {
        // O filtro é um objeto de campos opcionais; a camada de API espera um
        // dicionário aberto. Os nomes dos campos são exatamente os que o
        // Gateway declara em GET /expenses.
        query: filter as Record<string, string | undefined>,
    }).then((r) => r.expenses)

export const createExpense = (expense: ExpenseInput) =>
    api.post<{ message: string; expense: Expense }>('/expenses', expense)

export const updateExpense = (id: number, expense: ExpenseInput) =>
    api.put<{ message: string; expense: Expense }>(`/expenses/${id}`, expense)

export const deleteExpense = (id: number) =>
    api.delete<{ message: string }>(`/expenses/${id}`)

export const summary = (groupBy: string, filter: ExpenseFilter = {}) =>
    api.get<Summary>('/expenses/summary', { query: { group_by: groupBy, ...filter } })

// --- linguagem natural ------------------------------------------------------

export const interpret = (text: string) =>
    api.post<Interpretation>('/nlu/interpret', { text })
