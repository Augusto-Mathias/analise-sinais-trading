import json
import pandas as pd
import re

# Carregar JSON
with open('result.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

messages = data['messages']

# Função para extrair dados do texto do sinal
def parse_signal(text):
    # Exemplo de texto: "✅¹ AUDCAD-OTC - 11:33:00 - M1 - put - WIN"
    pattern = r'([✅❌🃏]+)\s*¹?\s*([\w\-]+)\s*-\s*([\d:]+)\s*-\s*(M\d+)\s*-\s*(put|call)\s*-\s*(WIN|LOSS|Doji)'
    match = re.search(pattern, text, re.IGNORECASE)
    if match:
        symbol = match.group(2)
        time = match.group(3)
        timeframe = match.group(4)
        direction = match.group(5).lower()
        result = match.group(6).capitalize()
        return {
            'symbol': symbol,
            'time': time,
            'timeframe': timeframe,
            'direction': direction,
            'result': result
        }
    return None

# Extrair sinais
signals = []
for msg in messages:
    parsed = parse_signal(msg['text'])
    if parsed:
        signals.append(parsed)

# Criar DataFrame
df = pd.DataFrame(signals)

# Mostrar resumo
print(df.head())
print(df['result'].value_counts())
print(df['symbol'].value_counts())

# Exemplo: calcular win rate geral
win_rate = (df['result'] == 'Win').mean()
print(f'Win rate geral: {win_rate:.2%}')