/**
 * Tradução das mensagens que vêm do backend.
 *
 * O servidor fala inglês — é a convenção do repositório, e uma mensagem de
 * protocolo não deveria mudar porque a tela mudou de idioma. Quem localiza é a
 * interface, aqui, no momento de exibir. O Diagnóstico é a exceção de
 * propósito: lá as respostas aparecem cruas, como vieram.
 *
 * Nada que não casar é inventado: a mensagem original passa direto. Uma
 * tradução faltando vira texto em inglês na tela, nunca texto errado.
 */

import { categoryLabel, methodLabel } from './format'

const METHOD_PT: Record<string, string> = { credit: 'crédito', debit: 'débito', any: 'qualquer' }

const method = (value: string) => METHOD_PT[value] ?? value

/** Cada regra é (padrão, como montar a frase em português). */
const RULES: [RegExp, (match: RegExpMatchArray) => string][] = [
    // --- CardService ---
    [/^(.+) \((\w+)\) registered$/, (m) => `${m[1]} (${method(m[2])}) cadastrado`],
    [/^(.+) \((\w+)\) was already registered$/, (m) => `${m[1]} (${method(m[2])}) já estava cadastrado`],
    [/^(.+) \((\w+)\) is registered$/, (m) => `${m[1]} (${method(m[2])}) está cadastrado`],
    [/^card (.+) is registered, but not for (\w+) \(only: (.+)\)$/,
        (m) => `o cartão ${m[1]} está cadastrado, mas não no ${method(m[2])} (só: ${m[3].split(', ').map(method).join(', ')})`],
    [/^card (.+) not found; registered: (.+)$/,
        (m) => `cartão ${m[1]} não encontrado. Cadastrados: ${m[2]}`],
    [/^card (.+) not found; no cards registered yet$/,
        (m) => `cartão ${m[1]} não encontrado — nenhum cartão cadastrado ainda`],
    [/^card name is required$/, () => 'o nome do cartão é obrigatório'],
    [/^payment method is required: CREDIT or DEBIT$/, () => 'informe o método: crédito ou débito'],

    // --- ExpenseService ---
    [/^expense #(\d+) recorded$/, (m) => `gasto #${m[1]} registrado`],
    [/^expense #(\d+) updated$/, (m) => `gasto #${m[1]} alterado`],
    [/^expense #(\d+) deleted$/, (m) => `gasto #${m[1]} removido`],
    [/^expense #(\d+) not found$/, (m) => `gasto #${m[1]} não encontrado`],
    [/^expense id is required$/, () => 'o id do gasto é obrigatório'],
    [/^product is required$/, () => 'o produto é obrigatório'],
    [/^amount must be greater than zero$/, () => 'o valor precisa ser maior que zero'],
    [/^cards service unavailable: (.+)$/,
        (m) => `o microsserviço de Cartões não respondeu (${m[1]})`],

    // --- servidor ---
    [/^which card was it\?$/, () => 'qual cartão foi?'],
    [/^was (.+) credit or debit\?$/, (m) => `o ${m[1]} foi no crédito ou no débito?`],
    [/^no valid card in the command$/, () => 'o comando não trouxe um cartão válido'],
    [/^command not understood$/, () => 'não entendi o comando'],
    [/^(\d+) expenses?$/, (m) => `${m[1]} ${m[1] === '1' ? 'gasto' : 'gastos'}`],
    [/^(\d+) cards?$/, (m) => `${m[1]} ${m[1] === '1' ? 'cartão' : 'cartões'}`],
    [/^total ([\d.]+)$/, (m) => `total ${Number(m[1]).toLocaleString('pt-BR', {
        style: 'currency', currency: 'BRL',
    })}`],
    [/^missing bearer token$/, () => 'requisição sem token'],
    [/^invalid or expired token$/, () => 'token inválido ou expirado'],
    [/^invalid username or password$/, () => 'usuário ou senha inválidos'],

    // --- validação do payload: "campo: motivo", vindo do Pydantic ---
    [/^(\w+): Field required$/, (m) => `${fieldLabel(m[1])}: campo obrigatório`],
    [/^(\w+): Input should be greater than 0$/, (m) => `${fieldLabel(m[1])}: precisa ser maior que zero`],
    [/^(\w+): String should have at least 1 character$/, (m) => `${fieldLabel(m[1])}: não pode ficar em branco`],
]

const FIELDS: Record<string, string> = {
    product: 'produto', amount: 'valor', card: 'cartão', method: 'método',
    category: 'categoria', date: 'data', description: 'descrição',
    name: 'nome', username: 'usuário', password: 'senha',
    start_date: 'data inicial', end_date: 'data final', group_by: 'agrupamento',
    text: 'texto',
}

const fieldLabel = (field: string) => FIELDS[field] ?? field

/** Traduz uma mensagem do backend. Sem regra que case, devolve como veio. */
export function translate(message: string | undefined | null): string {
    if (!message) return ''

    // O Gateway junta vários problemas de validação com "; ".
    if (message.includes('; ') && !message.includes('registered')) {
        return message.split('; ').map((part) => translate(part)).join('; ')
    }

    for (const [pattern, build] of RULES) {
        const match = message.match(pattern)
        if (match) return build(match)
    }

    // Mensagens de enum do Pydantic citam os valores aceitos; traduz os rótulos
    // conhecidos dentro da frase, que é longa demais para casar por inteiro.
    if (/^\w+: Input should be /.test(message)) {
        const [field, ...rest] = message.split(': ')
        const values = rest.join(': ').replace('Input should be ', '')
        return `${fieldLabel(field)}: use ${values
            .replace(/'/g, '')
            .split(/,| or /)
            .map((value) => value.trim())
            .filter(Boolean)
            .map((value) => (METHOD_PT[value.toLowerCase()] ? methodLabel(value) : categoryLabel(value)))
            .join(', ')}`
    }

    return message
}
