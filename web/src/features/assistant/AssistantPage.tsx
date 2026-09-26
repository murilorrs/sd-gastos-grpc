import React, { useEffect, useRef, useState } from 'react'
import { CornerDownLeft, Sparkles } from 'lucide-react'
import * as gateway from '@/shared/services/gateway'
import { ApiError } from '@/shared/services/api'
import {
    categoryLabel, formatDate, formatMoney, methodLabel, totalKeyLabel,
} from '@/shared/format'
import { Card } from '@/shared/ui/layout'
import { Button } from '@/shared/ui/forms'
import { Alert, Spinner } from '@/shared/ui/feedback'
import { translate } from '@/shared/messages'
import './AssistantPage.css'

const EXAMPLES = [
    'cadastra o Nubank no crédito e no débito',
    'gastei 89 reais num teclado mecânico no crédito do Nubank',
    'almoço de 42 reais no débito do Itaú ontem',
    'me mostra tudo que eu gastei no Nubank esse mês',
    'resumo por método',
]

interface Entry {
    id: number
    text: string
    loading: boolean
    interpretation?: gateway.Interpretation
    failure?: string
    /** Mensagem de quando o usuário completou um comando que faltava cartão. */
    completion?: string
}

let nextEntryId = 1

/**
 * O assistente: uma frase em português vira uma operação.
 *
 * Quem interpreta o texto é o servidor, em POST /nlu/interpret; o navegador só
 * manda a frase e recebe o resultado já executado. Quando falta a informação de
 * um cartão, a resposta volta com as opções em vez de gravar pela metade.
 */
const AssistantPage: React.FC = () => {
    const [text, setText] = useState('')
    const [entries, setEntries] = useState<Entry[]>([])
    const [busy, setBusy] = useState(false)
    const listRef = useRef<HTMLDivElement>(null)

    useEffect(() => {
        listRef.current?.scrollTo({ top: 0, behavior: 'smooth' })
    }, [entries.length])

    const send = async (command: string) => {
        const trimmed = command.trim()
        if (!trimmed || busy) return

        const id = nextEntryId++
        setEntries((current) => [{ id, text: trimmed, loading: true }, ...current])
        setText('')
        setBusy(true)

        try {
            const interpretation = await gateway.interpret(trimmed)
            setEntries((current) => current.map((entry) =>
                entry.id === id ? { ...entry, loading: false, interpretation } : entry))
        } catch (failure) {
            const message = failure instanceof ApiError && failure.status
                ? translate(failure.message)
                : 'Não foi possível conectar. Tente de novo.'
            setEntries((current) => current.map((entry) =>
                entry.id === id ? { ...entry, loading: false, failure: message } : entry))
        } finally {
            setBusy(false)
        }
    }

    /** Completa um comando que parou por falta de cartão ou de método. */
    const complete = async (
        entry: Entry, card: string, method: gateway.PaymentMethod, register: boolean,
    ) => {
        const pending = entry.interpretation?.pending
        if (!pending) return
        setBusy(true)
        try {
            if (register) await gateway.registerCard(card, method)
            const saved = await gateway.createExpense({
                product: String(pending.product || 'gasto'),
                description: String(pending.description || ''),
                amount: Number(pending.amount || 0),
                card,
                method,
                category: String(pending.category || 'other'),
                date: pending.date ? String(pending.date) : undefined,
            })
            setEntries((current) => current.map((item) =>
                item.id === entry.id ? { ...item, completion: translate(saved.message) } : item))
        } catch (failure) {
            const message = failure instanceof ApiError && failure.status
                ? translate(failure.message)
                : 'Não foi possível concluir. Tente de novo.'
            setEntries((current) => current.map((item) =>
                item.id === entry.id ? { ...item, completion: `x ${message}` } : item))
        } finally {
            setBusy(false)
        }
    }

    return (
        <>
            <div className="page-head">
                <div>
                    <h1>Assistente</h1>
                    <p>Escreva o que você gastou, do jeito que falaria.</p>
                </div>
            </div>

            <Card className="assistant-input-card">
                <form
                    className="assistant-form"
                    onSubmit={(event) => { event.preventDefault(); void send(text) }}
                >
                    <Sparkles size={18} className="assistant-form-icon" />
                    <input
                        className="assistant-input"
                        placeholder="gastei 89 reais num teclado no crédito do Nubank"
                        value={text}
                        onChange={(event) => setText(event.target.value)}
                        disabled={busy}
                        autoFocus
                    />
                    <Button type="submit" isLoading={busy} iconRight={<CornerDownLeft size={15} />}>
                        Enviar
                    </Button>
                </form>

                <div className="assistant-examples">
                    {EXAMPLES.map((example) => (
                        <button
                            key={example} type="button" className="assistant-example"
                            onClick={() => void send(example)} disabled={busy}
                        >
                            {example}
                        </button>
                    ))}
                </div>

            </Card>

            <div className="assistant-list" ref={listRef}>
                {entries.length === 0 && (
                    <p className="assistant-hint">
                        O que você pedir aparece aqui.
                    </p>
                )}
                {entries.map((entry) => (
                    <EntryCard key={entry.id} entry={entry} onComplete={complete} busy={busy} />
                ))}
            </div>
        </>
    )
}

// ---------------------------------------------------------------------------

const EntryCard: React.FC<{
    entry: Entry
    busy: boolean
    onComplete: (entry: Entry, card: string, method: gateway.PaymentMethod, register: boolean) => void
}> = ({ entry, busy, onComplete }) => (
    <Card className="assistant-entry">
        <p className="assistant-said">{entry.text}</p>

        {entry.loading && <div className="assistant-waiting"><Spinner size="sm" /> um momento…</div>}

        {entry.failure && <Alert variant="error">{entry.failure}</Alert>}

        {entry.interpretation && (
            <>
                <Outcome entry={entry} busy={busy} onComplete={onComplete} />

                {entry.completion && (
                    <Alert variant={entry.completion.startsWith('x ') ? 'error' : 'success'}>
                        {entry.completion.replace(/^x /, '')}
                    </Alert>
                )}
            </>
        )}
    </Card>
)

const Outcome: React.FC<{
    entry: Entry
    busy: boolean
    onComplete: (entry: Entry, card: string, method: gateway.PaymentMethod, register: boolean) => void
}> = ({ entry, busy, onComplete }) => {
    const result = entry.interpretation!
    const { status, action, message } = result

    if (status === 'unknown' || status === 'rejected') {
        return <Alert variant="warning">{translate(message) || 'Não entendi o pedido.'}</Alert>
    }

    // Faltou cartão ou método: em vez de descartar o pedido, oferece as saídas.
    if (status === 'needs_card' || status === 'needs_method') {
        const typed = String(result.pending?.card || '').trim()
        const known = (result.suggestions ?? []).flatMap((card) =>
            card.methods.map((method) => ({ card: card.name, method, register: false })))
        const wanted = String(result.pending?.method || '').toUpperCase()
        const offers = [
            ...known,
            ...(status === 'needs_card' && typed && wanted
                ? [{ card: typed, method: wanted as gateway.PaymentMethod, register: true }]
                : []),
        ]

        return (
            <div className="assistant-choice">
                <Alert variant="warning">{translate(message)}</Alert>
                <p className="muted">Como quer seguir?</p>
                <div className="assistant-offers">
                    {offers.map((offer) => (
                        <Button
                            key={`${offer.card}-${offer.method}-${offer.register}`}
                            size="sm" variant={offer.register ? 'primary' : 'secondary'}
                            disabled={busy || Boolean(entry.completion)}
                            onClick={() => onComplete(entry, offer.card, offer.method as gateway.PaymentMethod, offer.register)}
                        >
                            {offer.register
                                ? `cadastrar ${offer.card} (${methodLabel(offer.method)}) e lançar`
                                : `usar ${offer.card} (${methodLabel(offer.method)})`}
                        </Button>
                    ))}
                </div>
            </div>
        )
    }

    if (action === 'register_expense' && result.result?.expense) {
        const expense = result.result.expense
        return (
            <div className="assistant-result">
                <span className="assistant-result-icon">+</span>
                <div>
                    <strong>{expense.product}</strong>
                    <span className="muted">
                        {' '}#{expense.id} · {expense.card} / {methodLabel(expense.method)} ·{' '}
                        {categoryLabel(expense.category)} · {formatDate(expense.date)}
                    </span>
                </div>
                <span className="amount">{formatMoney(expense.amount)}</span>
            </div>
        )
    }

    if (action === 'search_expenses') {
        const expenses = result.result?.expenses ?? []
        if (expenses.length === 0) return <p className="muted">Nenhum gasto encontrado.</p>
        const total = expenses.reduce((sum, expense) => sum + expense.amount, 0)
        return (
            <div className="assistant-rows">
                {expenses.slice(0, 8).map((expense) => (
                    <div className="assistant-row" key={expense.id}>
                        <span>{expense.product}</span>
                        <span className="muted">
                            {expense.card} / {methodLabel(expense.method)} · {formatDate(expense.date)}
                        </span>
                        <span className="amount">{formatMoney(expense.amount)}</span>
                    </div>
                ))}
                <div className="assistant-row is-total">
                    <span>{expenses.length} {expenses.length === 1 ? 'gasto' : 'gastos'}</span>
                    <span />
                    <span className="amount">{formatMoney(total)}</span>
                </div>
            </div>
        )
    }

    if (action === 'summary') {
        const groupBy = result.result?.group_by ?? 'category'
        const totals = result.result?.totals ?? []
        if (totals.length === 0) return <p className="muted">Nada a somar por aqui.</p>
        return (
            <div className="assistant-rows">
                {totals.map((total) => (
                    <div className="assistant-row" key={total.key}>
                        <span>{totalKeyLabel(groupBy, total.key)}</span>
                        <span className="muted">{total.count}x</span>
                        <span className="amount">{formatMoney(total.total)}</span>
                    </div>
                ))}
                <div className="assistant-row is-total">
                    <span>Total</span>
                    <span />
                    <span className="amount">{formatMoney(result.result?.grand_total ?? 0)}</span>
                </div>
            </div>
        )
    }

    return <p className="assistant-plain">{translate(message)}</p>
}

export default AssistantPage
