import React, { useEffect, useMemo, useState } from 'react'
import { Receipt } from 'lucide-react'
import * as gateway from '@/shared/services/gateway'
import { ApiError } from '@/shared/services/api'
import { useMeta } from '@/shared/context/MetaContext'
import { categoryLabel, methodLabel, today } from '@/shared/format'
import { Modal, ModalBody, ModalFooter, ModalHeader, Alert } from '@/shared/ui/feedback'
import { Button, Input, Select, TextArea } from '@/shared/ui/forms'
import { translate } from '@/shared/messages'

interface Props {
    open: boolean
    cards: gateway.Card[]
    /** null = criando; um gasto = editando. */
    editing: gateway.Expense | null
    onClose: () => void
    onSaved: (message: string) => void
}

interface FormState {
    product: string
    amount: string
    card: string
    method: string
    category: string
    date: string
    description: string
}

const EMPTY: FormState = {
    product: '', amount: '', card: '', method: '', category: 'other',
    date: today(), description: '',
}

/**
 * O formulário de gasto — criação e edição no mesmo lugar, porque o corpo
 * enviado é o mesmo nos dois casos (POST /expenses e PUT /expenses/{id}).
 *
 * A validação daqui é só conforto: quem decide é o servidor, e a mensagem
 * exibida quando ele recusa é a dele.
 */
const ExpenseModal: React.FC<Props> = ({ open, cards, editing, onClose, onSaved }) => {
    const meta = useMeta()
    const [form, setForm] = useState<FormState>(EMPTY)
    const [error, setError] = useState<{ status: number; detail: string } | null>(null)
    const [saving, setSaving] = useState(false)

    useEffect(() => {
        if (!open) return
        setError(null)
        if (editing) {
            setForm({
                product: editing.product,
                amount: String(editing.amount),
                card: editing.card,
                method: editing.method,
                category: editing.category,
                date: editing.date,
                description: editing.description,
            })
        } else {
            setForm(EMPTY)
        }
    }, [open, editing])

    // Um cartão é a dupla (nome, método): oferecer um método que o cartão não
    // tem só serviria para o usuário levar um 400 desnecessário.
    const methodsOfCard = useMemo(() => {
        const found = cards.find((card) => card.name.toLowerCase() === form.card.toLowerCase())
        return found ? found.methods : []
    }, [cards, form.card])

    useEffect(() => {
        if (methodsOfCard.length === 1 && form.method !== methodsOfCard[0]) {
            setForm((state) => ({ ...state, method: methodsOfCard[0] }))
        }
    }, [methodsOfCard, form.method])

    const change = (field: keyof FormState) =>
        (event: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) =>
            setForm((state) => ({ ...state, [field]: event.target.value }))

    const submit = async (event: React.FormEvent) => {
        event.preventDefault()
        setSaving(true)
        setError(null)

        const payload: gateway.ExpenseInput = {
            product: form.product.trim(),
            description: form.description.trim(),
            // Number('') é 0, que o servidor recusa: campo obrigatório em
            // branco não deve virar um gasto de R$ 0.
            amount: Number(form.amount.replace(',', '.')),
            card: form.card.trim(),
            method: form.method as gateway.PaymentMethod,
            category: form.category,
            date: form.date || undefined,
        }

        try {
            const saved = editing
                ? await gateway.updateExpense(editing.id, payload)
                : await gateway.createExpense(payload)
            onSaved(saved.message)
            onClose()
        } catch (failure) {
            if (failure instanceof ApiError) {
                setError({ status: failure.status, detail: translate(failure.message) })
            } else {
                setError({ status: 0, detail: 'Não foi possível conectar. Tente de novo.' })
            }
        } finally {
            setSaving(false)
        }
    }

    return (
        <Modal isOpen={open} onClose={onClose} size="lg">
            <ModalHeader
                icon={<Receipt size={18} />}
                title={editing ? `Editar gasto #${editing.id}` : 'Novo gasto'}
            />
            <form onSubmit={submit}>
                <ModalBody>
                    {error && (
                        <Alert variant="error" title="Não foi possível salvar">
                            {error.detail}
                        </Alert>
                    )}

                    <div className="form-grid" style={{ marginTop: error ? 16 : 0 }}>
                        <Input
                            label="Produto" placeholder="teclado mecânico" className="span-2"
                            value={form.product} onChange={change('product')} disabled={saving}
                        />
                        <Input
                            label="Valor (R$)" placeholder="89,90" inputMode="decimal"
                            value={form.amount} onChange={change('amount')} disabled={saving}
                        />
                        <Input
                            label="Data" type="date"
                            value={form.date} onChange={change('date')} disabled={saving}
                        />
                        <Select
                            label="Cartão" placeholder="selecione" value={form.card}
                            onChange={change('card')} disabled={saving}
                            options={cards.map((card) => ({ value: card.name, label: card.name }))}
                        />
                        <Select
                            label="Método" placeholder="selecione" value={form.method}
                            onChange={change('method')} disabled={saving || !form.card}
                            helperText={form.card && methodsOfCard.length === 0
                                ? 'Este cartão não está cadastrado.' : undefined}
                            options={methodsOfCard.map((method) => ({
                                value: method, label: methodLabel(method),
                            }))}
                        />
                        <Select
                            label="Categoria" className="span-2" value={form.category}
                            onChange={change('category')} disabled={saving}
                            options={meta.categories.map((category) => ({
                                value: category, label: categoryLabel(category),
                            }))}
                        />
                        <TextArea
                            label="Descrição (opcional)" className="span-2" rows={2}
                            placeholder="detalhe que ajude a lembrar depois"
                            value={form.description} onChange={change('description')} disabled={saving}
                        />
                    </div>
                </ModalBody>
                <ModalFooter>
                    <Button type="button" variant="secondary" onClick={onClose} disabled={saving}>
                        Cancelar
                    </Button>
                    <Button type="submit" isLoading={saving}>
                        {editing ? 'Salvar alterações' : 'Registrar gasto'}
                    </Button>
                </ModalFooter>
            </form>
        </Modal>
    )
}

export default ExpenseModal
