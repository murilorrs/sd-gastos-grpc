"""Camada de linguagem natural, compartilhada pelo Gateway e pelo cliente.

Fica fora de gateway/ e de client/ porque os dois a usam: o Gateway interpreta
o texto que chega da interface web (POST /nlu/interpret), e o cliente de
terminal interpreta o que o usuário digita no REPL. Um módulo só, um prompt só
— duplicá-lo seria garantir que as duas pontas divergissem.

Nada aqui fala gRPC nem HTTP: a saída é um dict {"action": ..., "args": {...}}.
Quem despacha é quem chamou.
"""
