import React, { useEffect, useMemo, useState } from 'react'
import { Activity, CheckCircle2, Play, Trash2, XCircle } from 'lucide-react'
import * as gateway from '@/shared/services/gateway'
import {
    ApiError, ApiExchange, clearExchanges, getExchanges, subscribeExchanges,
} from '@/shared/services/api'
import { api } from '@/shared/services/api'
import { Card } from '@/shared/ui/layout'
import { Badge, EmptyState } from '@/shared/ui/data-display'
import { Button } from '@/shared/ui/forms'
import { Alert } from '@/shared/ui/feedback'
import './DiagnosticsPage.css'

/**
 * Diagnóstico: verificações automáticas da API.
 *
 * Cada botão dispara uma requisição de verdade e compara o status recebido com
 * o esperado. Serve para conferir, em segundos, que a autenticação está
 * barrando quem deve, que a validação está recusando o que deve, e que as
 * operações válidas chegam ao banco.
 *
 * O painel da direita é um registro vivo: além das verificações, toda chamada
 * feita em qualquer tela do sistema aparece nele.
 */

interface Scenario {
    id: string
    group: '401' | '400' | 'sucesso'
    title: string
    detail: string
    /** Os status aceitáveis. Mais de um quando a resposta depende do estado. */
    expected: number[]
    run: (context: { card?: gateway.Card }) => Promise<unknown>
}

const VALID_EXPENSE = {
    product: 'teclado mecânico',
    description: 'verificação automática',
    amount: 89.9,
    category: 'technology',
}

const SCENARIOS: Scenario[] = [
    {
        id: 'no-token',
        group: '401',
        title: 'Requisição sem credenciais',
        detail: 'Uma requisição sem credenciais precisa ser recusada.',
        expected: [401],
        run: () => api.get('/expenses', { auth: 'none', keepSessionOn401: true }),
    },
    {
        id: 'bad-token',
        group: '401',
        title: 'Sessão inválida',
        detail: 'Uma sessão forjada ou expirada não pode dar acesso aos dados.',
        expected: [401],
        run: () => api.get('/expenses', { auth: 'invalid', keepSessionOn401: true }),
    },
    {
        id: 'bad-credentials',
        group: '401',
        title: 'Senha incorreta',
        detail: 'O login precisa recusar credenciais erradas.',
        expected: [401],
        run: () => gateway.login('demo', 'senha-errada'),
    },
    {
        id: 'missing-fields',
        group: '400',
        title: 'Campos obrigatórios em branco',
        detail: 'Um gasto sem produto, valor, cartão e método não pode ser aceito.',
        expected: [400],
        run: () => api.post('/expenses', {}),
    },
    {
        id: 'zero-amount',
        group: '400',
        title: 'Valor igual a zero',
        detail: 'Um gasto de R$ 0 não é um gasto.',
        expected: [400],
        run: ({ card }) => api.post('/expenses', {
            ...VALID_EXPENSE, amount: 0,
            card: card?.name ?? 'Nubank', method: card?.methods[0] ?? 'CREDIT',
        }),
    },
    {
        id: 'bad-category',
        group: '400',
        title: 'Categoria inexistente',
        detail: 'Só as categorias do sistema são aceitas.',
        expected: [400],
        run: ({ card }) => api.post('/expenses', {
            ...VALID_EXPENSE, category: 'criptomoedas',
            card: card?.name ?? 'Nubank', method: card?.methods[0] ?? 'CREDIT',
        }),
    },
    {
        id: 'bad-date',
        group: '400',
        title: 'Data em formato errado',
        detail: 'Datas fora do formato AAAA-MM-DD precisam ser recusadas.',
        expected: [400],
        run: () => api.get('/expenses', { query: { start_date: 'ontem' } }),
    },
    {
        id: 'broken-json',
        group: '400',
        title: 'Requisição corrompida',
        detail: 'Dados que chegam quebrados não podem derrubar o servidor.',
        expected: [400],
        run: () => api.post('/expenses', undefined, { rawBody: '{"product": "teclado", ' }),
    },
    {
        id: 'unknown-card',
        group: '400',
        title: 'Cartão que não existe',
        detail: 'Um gasto só pode ser lançado num cartão que existe.',
        expected: [400],
        run: () => api.post('/expenses', {
            ...VALID_EXPENSE, card: 'Banco Inventado', method: 'CREDIT',
        }),
    },
    {
        id: 'create-card',
        group: 'sucesso',
        title: 'Cadastrar cartão',
        detail: 'Cartão novo é criado; o mesmo cartão de novo não duplica. Dispare duas vezes para ver a diferença.',
        expected: [201, 200],
        run: () => gateway.registerCard('Cartão de teste', 'CREDIT'),
    },
    {
        id: 'create-expense',
        group: 'sucesso',
        title: 'Registrar gasto',
        detail: 'Um lançamento válido precisa ser gravado. Cada disparo cria um registro novo.',
        expected: [201],
        run: ({ card }) => api.post('/expenses', {
            ...VALID_EXPENSE,
            card: card?.name ?? 'Cartão de teste',
            method: card?.methods[0] ?? 'CREDIT',
        }),
    },
    {
        id: 'search',
        group: 'sucesso',
        title: 'Consultar gastos',
        detail: 'A consulta precisa devolver a lista gravada.',
        expected: [200],
        run: () => api.get('/expenses'),
    },
]

const GROUPS: { id: Scenario['group']; label: string; hint: string }[] = [
    { id: '401', label: 'Acesso', hint: 'quem não está autenticado não passa' },
    { id: '400', label: 'Validação', hint: 'dados inválidos são recusados' },
    { id: 'sucesso', label: 'Operações', hint: 'o caminho normal, até o banco' },
]

const DiagnosticsPage: React.FC = () => {
    const [exchanges, setExchanges] = useState<ApiExchange[]>(getExchanges())
    const [running, setRunning] = useState<string | null>(null)
    const [results, setResults] = useState<Record<string, number>>({})
    const [cards, setCards] = useState<gateway.Card[]>([])

    useEffect(() => subscribeExchanges(setExchanges), [])
    useEffect(() => { void gateway.listCards().then(setCards).catch(() => undefined) }, [results])

    // Os cenários de sucesso precisam de um cartão que exista de verdade.
    const card = useMemo(() => cards[0], [cards])

    const run = async (scenario: Scenario) => {
        setRunning(scenario.id)
        try {
            await scenario.run({ card })
        } catch (failure) {
            // Um 4xx é o resultado esperado de quase toda verificação daqui: o
            // erro já foi registrado no histórico, que é de onde o status sai.
            if (!(failure instanceof ApiError)) throw failure
        }
        const latest = getExchanges()[0]
        setResults((current) => ({ ...current, [scenario.id]: latest?.status ?? 0 }))
        setRunning(null)
    }

    const runAll = async () => {
        for (const scenario of SCENARIOS) {
            // eslint-disable-next-line no-await-in-loop
            await run(scenario)
        }
    }

    return (
        <>
            <div className="page-head">
                <div>
                    <h1>Diagnóstico</h1>
                    <p>
                        Verificações automáticas da API. Cada uma dispara uma requisição de
                        verdade e compara a resposta com o esperado.
                    </p>
                </div>
                <div className="page-head-actions">
                    <Button variant="secondary" iconLeft={<Play size={15} />} onClick={runAll}
                        disabled={Boolean(running)}>
                        Verificar tudo
                    </Button>
                    <Button variant="ghost" iconLeft={<Trash2 size={15} />} onClick={clearExchanges}>
                        Limpar registro
                    </Button>
                </div>
            </div>

            {!card && (
                <Alert variant="warning" title="Nenhum cartão cadastrado">
                    As verificações de operação precisam de um cartão. Rode primeiro
                    “Cadastrar cartão”, ou cadastre um na aba Cartões.
                </Alert>
            )}

            <div className="diag-layout">
                <div className="stack">
                    {GROUPS.map((group) => (
                        <Card key={group.id}>
                            <div className="card-head">
                                <div>
                                    <h2>{group.label}</h2>
                                    <p>{group.hint}</p>
                                </div>
                            </div>
                            <ul className="diag-scenarios">
                                {SCENARIOS.filter((scenario) => scenario.group === group.id).map((scenario) => (
                                    <li key={scenario.id}>
                                        <div className="diag-scenario-text">
                                            <strong>{scenario.title}</strong>
                                            <span className="muted">{scenario.detail}</span>
                                        </div>
                                        <div className="diag-scenario-run">
                                            {/* Esperado à esquerda, obtido à direita. */}
                                            {results[scenario.id] !== undefined && (
                                                <span className={`diag-verdict${
                                                    scenario.expected.includes(results[scenario.id]) ? ' is-ok' : ''}`}>
                                                    {scenario.expected.includes(results[scenario.id])
                                                        ? <CheckCircle2 size={13} />
                                                        : <XCircle size={13} />}
                                                    esperado {scenario.expected.join(' ou ')} · recebido{' '}
                                                    {results[scenario.id] || '—'}
                                                </span>
                                            )}
                                            <Button
                                                size="sm" variant="secondary"
                                                isLoading={running === scenario.id}
                                                disabled={Boolean(running)}
                                                onClick={() => void run(scenario)}
                                            >
                                                verificar
                                            </Button>
                                        </div>
                                    </li>
                                ))}
                            </ul>
                        </Card>
                    ))}
                </div>

                <Card noPadding className="diag-log-card">
                    <div className="diag-log-head">
                        <span>Requisições · mais recente no topo</span>
                        <span className="muted">{exchanges.length}</span>
                    </div>
                    {exchanges.length === 0 ? (
                        <EmptyState
                            icon={<Activity size={28} />}
                            title="Nada registrado ainda"
                            description="Rode uma verificação ao lado — ou navegue pelo sistema: toda requisição aparece aqui."
                        />
                    ) : (
                        <ul className="diag-log">
                            {exchanges.map((exchange) => (
                                <ExchangeRow key={exchange.id} exchange={exchange} />
                            ))}
                        </ul>
                    )}
                </Card>
            </div>
        </>
    )
}

function statusVariant(status: number): 'success' | 'danger' | 'warning' | 'gray' {
    if (status === 0) return 'gray'
    if (status < 300) return 'success'
    if (status === 401 || status === 403) return 'warning'
    return 'danger'
}

const ExchangeRow: React.FC<{ exchange: ApiExchange }> = ({ exchange }) => {
    const [open, setOpen] = useState(false)
    const ok = exchange.status > 0 && exchange.status < 300

    return (
        <li className="diag-log-item">
            <button className="diag-log-summary" onClick={() => setOpen(!open)}>
                <Badge variant={statusVariant(exchange.status)} styleType="solid">
                    {exchange.status || '—'}
                </Badge>
                <span className="diag-log-method">{exchange.method}</span>
                <span className="diag-log-path mono">{exchange.path}</span>
                <span className="diag-log-token" title="credenciais enviadas">
                    {exchange.sentToken === 'valid' && <CheckCircle2 size={13} />}
                    {exchange.sentToken !== 'valid' && <XCircle size={13} />}
                    {exchange.sentToken === 'valid' ? 'sessão' : exchange.sentToken === 'invalid' ? 'inválida' : 'ausente'}
                </span>
                <span className="muted">{exchange.ms} ms</span>
            </button>

            {open && (
                <div className="diag-log-detail">
                    {exchange.requestBody !== null && (
                        <>
                            <p className="diag-log-label">enviado</p>
                            <pre className={ok ? '' : 'is-bad'}>
                                {typeof exchange.requestBody === 'string'
                                    ? exchange.requestBody
                                    : JSON.stringify(exchange.requestBody, null, 2)}
                            </pre>
                        </>
                    )}
                    <p className="diag-log-label">resposta · {exchange.at}</p>
                    <pre>{JSON.stringify(exchange.responseBody, null, 2)}</pre>
                </div>
            )}
        </li>
    )
}

export default DiagnosticsPage
