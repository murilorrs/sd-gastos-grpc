import React, { useCallback, useEffect, useState } from 'react'
import { CheckCircle2, CreditCard, Plus, Search, XCircle } from 'lucide-react'
import * as gateway from '@/shared/services/gateway'
import { ApiError } from '@/shared/services/api'
import { useMeta } from '@/shared/context/MetaContext'
import { useToast } from '@/shared/hooks/useToast'
import { methodLabel } from '@/shared/format'
import { Card } from '@/shared/ui/layout'
import { Badge, EmptyState } from '@/shared/ui/data-display'
import { Button, Input, Select } from '@/shared/ui/forms'
import { Alert, Spinner, ToastContainer } from '@/shared/ui/feedback'
import { translate } from '@/shared/messages'
import './CardsPage.css'

/**
 * Cartões. Um cartão é a dupla (nome, método) — "Nubank crédito" e "Nubank
 * débito" são dois registros —, e é por isso que a tela agrupa por nome e
 * mostra os métodos como etiquetas.
 */
const CardsPage: React.FC = () => {
    const meta = useMeta()
    const { toasts, dismiss, success, info, error: toastError } = useToast()

    const [cards, setCards] = useState<gateway.Card[]>([])
    const [loading, setLoading] = useState(true)
    const [name, setName] = useState('')
    const [method, setMethod] = useState<string>('CREDIT')
    const [saving, setSaving] = useState(false)
    const [formError, setFormError] = useState<string | null>(null)

    const [probe, setProbe] = useState('')
    const [probeResult, setProbeResult] = useState<gateway.Validation | null>(null)
    const [probing, setProbing] = useState(false)

    const load = useCallback(async () => {
        setLoading(true)
        try {
            setCards(await gateway.listCards())
        } catch (failure) {
            toastError('Não foi possível carregar os cartões.', 'Erro')
        } finally {
            setLoading(false)
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [])

    useEffect(() => { void load() }, [load])

    const register = async (event: React.FormEvent) => {
        event.preventDefault()
        setSaving(true)
        setFormError(null)
        try {
            const response = await gateway.registerCard(name.trim(), method as gateway.PaymentMethod)
            // created=false: o cartão já existia, e nada foi criado.
            if (response.created) success(translate(response.message), 'Cartão cadastrado')
            else info(translate(response.message), 'Já estava cadastrado')
            setName('')
            await load()
        } catch (failure) {
            setFormError(failure instanceof ApiError
                ? translate(failure.message)
                : 'Não foi possível cadastrar o cartão.')
        } finally {
            setSaving(false)
        }
    }

    const validate = async (event: React.FormEvent) => {
        event.preventDefault()
        if (!probe.trim()) return
        setProbing(true)
        try {
            setProbeResult(await gateway.validateCard(probe.trim()))
        } catch (failure) {
            toastError('Não foi possível verificar o cartão.', 'Erro')
        } finally {
            setProbing(false)
        }
    }

    return (
        <>
            <ToastContainer toasts={toasts} onDismiss={dismiss} />

            <div className="page-head">
                <div>
                    <h1>Cartões</h1>
                </div>
            </div>

            <div className="cards-layout">
                <div className="stack">
                    <Card>
                        <div className="card-head">
                            <h2>Cadastrar cartão</h2>
                        </div>

                        {formError && <Alert variant="error">{formError}</Alert>}

                        <form className="cards-form" onSubmit={register}>
                            <Input
                                label="Nome" placeholder="Nubank" value={name}
                                onChange={(event) => setName(event.target.value)} disabled={saving}
                            />
                            <Select
                                label="Método" value={method} disabled={saving}
                                onChange={(event) => setMethod(event.target.value)}
                                options={meta.methods.map((option) => ({
                                    value: option, label: methodLabel(option),
                                }))}
                            />
                            <Button type="submit" iconLeft={<Plus size={16} />} isLoading={saving}>
                                Cadastrar
                            </Button>
                        </form>
                    </Card>

                    <Card>
                        <div className="card-head">
                            <h2>Verificar um cartão</h2>
                        </div>

                        <form className="cards-form" onSubmit={validate}>
                            <Input
                                label="Nome do cartão" placeholder="Nubank" value={probe}
                                onChange={(event) => setProbe(event.target.value)} disabled={probing}
                            />
                            <Button type="submit" variant="secondary"
                                iconLeft={<Search size={16} />} isLoading={probing}>
                                Verificar
                            </Button>
                        </form>

                        {probeResult && (
                            <div className={`probe-result${probeResult.exists ? ' is-ok' : ''}`}>
                                {probeResult.exists
                                    ? <CheckCircle2 size={18} />
                                    : <XCircle size={18} />}
                                <div>
                                    <p>{translate(probeResult.message)}</p>
                                    {!probeResult.exists && probeResult.suggestions.length > 0 && (
                                        <p className="muted">
                                            Parecidos: {probeResult.suggestions.map((s) => s.name).join(', ')}
                                        </p>
                                    )}
                                </div>
                            </div>
                        )}
                    </Card>
                </div>

                <Card>
                    <div className="card-head">
                        <div>
                            <h2>Cadastrados</h2>
                            <p>ListCards · {cards.length} {cards.length === 1 ? 'cartão' : 'cartões'}</p>
                        </div>
                    </div>

                    {loading ? (
                        <div className="cards-loading"><Spinner /></div>
                    ) : cards.length === 0 ? (
                        <EmptyState
                            icon={<CreditCard size={28} />}
                            title="Nenhum cartão ainda"
                            description="Cadastre um ao lado. Todo gasto é lançado num cartão."
                        />
                    ) : (
                        <ul className="cards-grid">
                            {cards.map((card) => (
                                <li key={card.name} className="card-chip">
                                    <span className="card-chip-icon"><CreditCard size={18} /></span>
                                    <div>
                                        <strong>{card.name}</strong>
                                        <div className="card-chip-methods">
                                            {card.methods.map((value) => (
                                                <Badge
                                                    key={value}
                                                    variant={value === 'CREDIT' ? 'primary' : 'info'}
                                                >
                                                    {methodLabel(value)}
                                                </Badge>
                                            ))}
                                        </div>
                                    </div>
                                </li>
                            ))}
                        </ul>
                    )}
                </Card>
            </div>
        </>
    )
}

export default CardsPage
