/**
 * A única porta de saída do frontend.
 *
 * Todo pedido sai daqui para o API Gateway — o frontend não conhece, e não
 * consegue alcançar, nenhum microsserviço gRPC. A base é o caminho relativo
 * "/api": em desenvolvimento quem o repassa ao Gateway é o proxy do Vite, em
 * produção é o nginx da vm-client. Nos dois casos o navegador vê uma origem
 * só, e não existe requisição cross-origin.
 *
 * Cada chamada também é registrada num histórico em memória. É o que a página
 * de Diagnóstico exibe: método, rota, corpo enviado, status e corpo recebido.
 */

export const API_BASE = '/api'

export const UNAUTHORIZED_EVENT = 'grana:unauthorized'

const TOKEN_KEY = 'grana:token'

let token: string | null = sessionStorage.getItem(TOKEN_KEY)

export function setToken(value: string | null): void {
    token = value
    if (value) sessionStorage.setItem(TOKEN_KEY, value)
    else sessionStorage.removeItem(TOKEN_KEY)
}

export function getToken(): string | null {
    return token
}

// ---------------------------------------------------------------------------
// Histórico das trocas HTTP
// ---------------------------------------------------------------------------

export interface ApiExchange {
    id: number
    at: string
    method: string
    path: string
    requestBody: unknown
    sentToken: 'valid' | 'invalid' | 'none'
    status: number
    responseBody: unknown
    ms: number
}

const MAX_EXCHANGES = 40
let exchanges: ApiExchange[] = []
let nextId = 1
const listeners = new Set<(list: ApiExchange[]) => void>()

function record(exchange: Omit<ApiExchange, 'id' | 'at'>): void {
    const full: ApiExchange = {
        ...exchange,
        id: nextId++,
        at: new Date().toLocaleTimeString('pt-BR'),
    }
    exchanges = [full, ...exchanges].slice(0, MAX_EXCHANGES)
    listeners.forEach((listener) => listener(exchanges))
}

export function getExchanges(): ApiExchange[] {
    return exchanges
}

export function clearExchanges(): void {
    exchanges = []
    listeners.forEach((listener) => listener(exchanges))
}

export function subscribeExchanges(listener: (list: ApiExchange[]) => void): () => void {
    listeners.add(listener)
    return () => {
        listeners.delete(listener)
    }
}

// ---------------------------------------------------------------------------
// Requisição
// ---------------------------------------------------------------------------

/** O erro que as páginas tratam: traz o status HTTP que o Gateway devolveu. */
export class ApiError extends Error {
    constructor(readonly status: number, message: string, readonly body?: unknown) {
        super(message)
        this.name = 'ApiError'
    }
}

export interface RequestOptions {
    /** 'none' omite o cabeçalho; 'invalid' manda um token falso (usado no Diagnóstico). */
    auth?: 'default' | 'none' | 'invalid'
    /** Corpo cru, sem passar por JSON.stringify — para demonstrar JSON malformado. */
    rawBody?: string
    /** Não deslogar diante de um 401: o Diagnóstico provoca 401 de propósito. */
    keepSessionOn401?: boolean
    query?: Record<string, string | number | undefined | null>
}

function withQuery(path: string, query?: RequestOptions['query']): string {
    if (!query) return path
    const params = new URLSearchParams()
    Object.entries(query).forEach(([key, value]) => {
        if (value !== undefined && value !== null && value !== '') {
            params.append(key, String(value))
        }
    })
    const search = params.toString()
    return search ? `${path}?${search}` : path
}

async function request<T>(
    method: string,
    path: string,
    body?: unknown,
    options: RequestOptions = {},
): Promise<T> {
    const url = withQuery(path, options.query)
    const headers: Record<string, string> = {}
    const authMode = options.auth ?? 'default'

    if (body !== undefined || options.rawBody !== undefined) {
        headers['Content-Type'] = 'application/json'
    }
    if (authMode === 'default' && token) {
        headers['Authorization'] = `Bearer ${token}`
    }
    if (authMode === 'invalid') {
        headers['Authorization'] = 'Bearer token-invalido-de-propósito'
    }

    const payload = options.rawBody ?? (body === undefined ? undefined : JSON.stringify(body))
    const started = performance.now()

    let response: Response
    try {
        response = await fetch(API_BASE + url, { method, headers, body: payload })
    } catch {
        record({
            method, path: url, requestBody: options.rawBody ?? body ?? null,
            sentToken: authMode === 'default' ? (token ? 'valid' : 'none') : authMode === 'invalid' ? 'invalid' : 'none',
            status: 0, responseBody: { detail: 'sem resposta do servidor' },
            ms: Math.round(performance.now() - started),
        })
        throw new ApiError(0, 'Não foi possível conectar ao servidor.')
    }

    const text = await response.text()
    let data: unknown = null
    try {
        data = text ? JSON.parse(text) : null
    } catch {
        data = text
    }

    record({
        method,
        path: url,
        requestBody: options.rawBody ?? body ?? null,
        sentToken: authMode === 'default' ? (token ? 'valid' : 'none')
            : authMode === 'invalid' ? 'invalid' : 'none',
        status: response.status,
        responseBody: data,
        ms: Math.round(performance.now() - started),
    })

    if (response.status === 401 && authMode === 'default' && !options.keepSessionOn401) {
        // O token venceu (uma hora) ou não existe: a sessão acabou de verdade.
        setToken(null)
        window.dispatchEvent(new CustomEvent(UNAUTHORIZED_EVENT))
    }

    if (!response.ok) {
        const detail = (data as { detail?: string } | null)?.detail
        throw new ApiError(response.status, detail || `HTTP ${response.status}`, data)
    }

    return data as T
}

export const api = {
    get: <T>(path: string, options?: RequestOptions) => request<T>('GET', path, undefined, options),
    post: <T>(path: string, body?: unknown, options?: RequestOptions) => request<T>('POST', path, body, options),
    put: <T>(path: string, body?: unknown, options?: RequestOptions) => request<T>('PUT', path, body, options),
    delete: <T>(path: string, options?: RequestOptions) => request<T>('DELETE', path, undefined, options),
}
