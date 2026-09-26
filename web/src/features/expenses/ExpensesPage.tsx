import React, { useCallback, useEffect, useState } from 'react'
import { Pencil, Plus, Receipt, RotateCcw, Trash2 } from 'lucide-react'
import * as gateway from '@/shared/services/gateway'
import { ApiError } from '@/shared/services/api'
import { useMeta } from '@/shared/context/MetaContext'
import { useToast } from '@/shared/hooks/useToast'
import { categoryLabel, formatDate, formatMoney, methodLabel } from '@/shared/format'
import { Card } from '@/shared/ui/layout'
import { Badge, EmptyState, Table, Tbody, Td, Th, Thead, Tr } from '@/shared/ui/data-display'
import { Button, IconButton, Input, Select } from '@/shared/ui/forms'
import { Modal, ModalBody, ModalFooter, ModalHeader, Spinner, ToastContainer } from '@/shared/ui/feedback'
import { translate } from '@/shared/messages'
import ExpenseModal from './ExpenseModal'
import './ExpensesPage.css'

const EMPTY_FILTER = { card: '', method: '', category: '', start_date: '', end_date: '' }

/**
 * A tabela de gastos e o ciclo completo de um lançamento: criar, alterar e
 * remover.
 */
const ExpensesPage: React.FC = () => {
    const meta = useMeta()
    const { toasts, dismiss, success, error: toastError } = useToast()

    const [filter, setFilter] = useState(EMPTY_FILTER)
    const [expenses, setExpenses] = useState<gateway.Expense[]>([])
    const [cards, setCards] = useState<gateway.Card[]>([])
    const [loading, setLoading] = useState(true)
    const [formOpen, setFormOpen] = useState(false)
    const [editing, setEditing] = useState<gateway.Expense | null>(null)
    const [removing, setRemoving] = useState<gateway.Expense | null>(null)
    const [deleting, setDeleting] = useState(false)

    // O filtro entra por parâmetro, e não pelas dependências, para o botão
    // "Filtrar" poder aplicar o estado novo sem esperar o próximo render.
    const load = useCallback(async (applied: typeof EMPTY_FILTER) => {
        setLoading(true)
        try {
            const [found, registered] = await Promise.all([
                gateway.listExpenses(applied),
                gateway.listCards(),
            ])
            setExpenses(found)
            setCards(registered)
        } catch (failure) {
            toastError(failure instanceof Error ? translate(failure.message) : 'Não foi possível carregar os gastos.', 'Erro')
        } finally {
            setLoading(false)
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [])

    useEffect(() => { void load(EMPTY_FILTER) }, [load])

    const change = (field: keyof typeof EMPTY_FILTER) =>
        (event: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
            setFilter((state) => ({ ...state, [field]: event.target.value }))

    const clearFilter = () => {
        setFilter(EMPTY_FILTER)
        void load(EMPTY_FILTER)
    }

    const confirmDelete = async () => {
        if (!removing) return
        setDeleting(true)
        try {
            const response = await gateway.deleteExpense(removing.id)
            success(translate(response.message), 'Removido')
            setRemoving(null)
            await load(filter)
        } catch (failure) {
            const detail = failure instanceof ApiError
                ? translate(failure.message)
                : 'Não foi possível remover o gasto.'
            toastError(detail, 'Não removido')
        } finally {
            setDeleting(false)
        }
    }

    const total = expenses.reduce((sum, expense) => sum + expense.amount, 0)

    return (
        <>
            <ToastContainer toasts={toasts} onDismiss={dismiss} />

            <div className="page-head">
                <div>
                    <h1>Gastos</h1>
                </div>
                <div className="page-head-actions">
                    <Button
                        iconLeft={<Plus size={16} />}
                        onClick={() => { setEditing(null); setFormOpen(true) }}
                    >
                        Novo gasto
                    </Button>
                </div>
            </div>

            <Card className="expenses-filters">
                <div className="filter-bar">
                    <Select
                        label="Cartão" value={filter.card}
                        onChange={change('card')}
                        options={[{ value: '', label: 'Todos' },
                            ...cards.map((card) => ({ value: card.name, label: card.name }))]}
                    />
                    <Select
                        label="Método" value={filter.method} onChange={change('method')}
                        options={[{ value: '', label: 'Todos' },
                            ...meta.methods.map((method) => ({ value: method, label: methodLabel(method) }))]}
                    />
                    <Select
                        label="Categoria" value={filter.category} onChange={change('category')}
                        options={[{ value: '', label: 'Todas' },
                            ...meta.categories.map((category) => ({
                                value: category, label: categoryLabel(category),
                            }))]}
                    />
                    <Input label="De" type="date" value={filter.start_date} onChange={change('start_date')} />
                    <Input label="Até" type="date" value={filter.end_date} onChange={change('end_date')} />
                    <div className="filter-bar-actions">
                        <Button variant="secondary" onClick={() => void load(filter)}>Filtrar</Button>
                        <IconButton
                            variant="ghost" icon={<RotateCcw size={16} />}
                            aria-label="Limpar filtros" onClick={clearFilter}
                        />
                    </div>
                </div>
            </Card>

            <Card noPadding className="expenses-table-card">
                <div className="expenses-table-head">
                    <span>
                        {loading ? 'buscando…'
                            : `${expenses.length} ${expenses.length === 1 ? 'gasto' : 'gastos'}`}
                    </span>
                    <span className="amount">{formatMoney(total)}</span>
                </div>

                {loading ? (
                    <div className="expenses-loading"><Spinner /></div>
                ) : expenses.length === 0 ? (
                    <EmptyState
                        icon={<Receipt size={28} />}
                        title="Nenhum gasto encontrado"
                        description="Ajuste os filtros ou registre um novo lançamento."
                        action={
                            <Button iconLeft={<Plus size={16} />}
                                onClick={() => { setEditing(null); setFormOpen(true) }}>
                                Novo gasto
                            </Button>
                        }
                    />
                ) : (
                    <Table>
                        <Thead>
                            <Tr>
                                <Th>#</Th>
                                <Th>Produto</Th>
                                <Th>Categoria</Th>
                                <Th>Cartão</Th>
                                <Th>Data</Th>
                                <Th align="right">Valor</Th>
                                <Th align="right">Ações</Th>
                            </Tr>
                        </Thead>
                        <Tbody>
                            {expenses.map((expense) => (
                                <Tr key={expense.id}>
                                    <Td><span className="mono muted">{expense.id}</span></Td>
                                    <Td>
                                        <div className="expense-product">
                                            <strong>{expense.product}</strong>
                                            {expense.description && (
                                                <span className="muted">{expense.description}</span>
                                            )}
                                        </div>
                                    </Td>
                                    <Td><Badge variant="gray">{categoryLabel(expense.category)}</Badge></Td>
                                    <Td>
                                        {expense.card}
                                        <Badge
                                            variant={expense.method === 'CREDIT' ? 'primary' : 'info'}
                                            className="table-tag"
                                        >
                                            {methodLabel(expense.method)}
                                        </Badge>
                                    </Td>
                                    <Td>{formatDate(expense.date)}</Td>
                                    <Td align="right"><span className="amount">{formatMoney(expense.amount)}</span></Td>
                                    <Td align="right">
                                        <div className="expense-actions">
                                            <IconButton
                                                size="sm" variant="ghost" icon={<Pencil size={15} />}
                                                aria-label={`Editar gasto ${expense.id}`}
                                                onClick={() => { setEditing(expense); setFormOpen(true) }}
                                            />
                                            <IconButton
                                                size="sm" variant="ghost" icon={<Trash2 size={15} />}
                                                aria-label={`Remover gasto ${expense.id}`}
                                                onClick={() => setRemoving(expense)}
                                            />
                                        </div>
                                    </Td>
                                </Tr>
                            ))}
                        </Tbody>
                    </Table>
                )}
            </Card>

            <ExpenseModal
                open={formOpen}
                cards={cards}
                editing={editing}
                onClose={() => setFormOpen(false)}
                onSaved={(message) => { success(translate(message), 'Salvo'); void load(filter) }}
            />

            <Modal isOpen={Boolean(removing)} onClose={() => setRemoving(null)} size="sm">
                <ModalHeader icon={<Trash2 size={18} />} title="Remover gasto" />
                <ModalBody>
                    <p className="confirm-text">
                        <strong>{removing?.product}</strong> será removido em definitivo.
                        Esta ação não pode ser desfeita.
                    </p>
                </ModalBody>
                <ModalFooter>
                    <Button variant="secondary" onClick={() => setRemoving(null)} disabled={deleting}>
                        Cancelar
                    </Button>
                    <Button variant="danger" onClick={confirmDelete} isLoading={deleting}>
                        Remover
                    </Button>
                </ModalFooter>
            </Modal>
        </>
    )
}

export default ExpensesPage
