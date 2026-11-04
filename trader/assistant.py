"""Explain the SAME OHLC that generated the chart; no screenshot-vision claim."""
import json
from .strategy import indicators


def numeric_context(frame, decision, epic, resolution, spread):
    df = indicators(frame)
    recent = df.tail(12)
    payload = {'instrument': epic, 'resolution': resolution,
      'last_closed_utc':frame.index[-1].isoformat(), 'spread_pts':spread,
      'strategy':decision.strategy,'decision':decision.action,
      'reason':decision.reason,'entry':decision.entry,'stop':decision.stop,
      'target':decision.target,'rr':decision.rr,
      'last_12_closed_candles': []}
    for t, row in recent.iterrows():
        payload['last_12_closed_candles'].append({'t':t.isoformat(), **{
            k:round(float(row[k]),3) for k in ['Open','High','Low','Close','EMA9','EMA21','EMA50','ATR','RSI']}})
    return payload


def answer_ai(api_key, model, question, payload, effort='high'):
    if not api_key:
        return 'Brak OPENAI_API_KEY. Analiza regułowa znajduje się w panelu. Chat AI nie był uruchomiony.'
    try:
        if effort not in {'low','medium','high','xhigh'}:
            return 'Niepoprawny OPENAI_REASONING_EFFORT — ustaw low/medium/high/xhigh.'
        from openai import OpenAI
        response = OpenAI(api_key=api_key,timeout=45).responses.create(
           model=model, reasoning={'effort':effort}, max_output_tokens=3500,
           instructions=('Jesteś asystentem badawczym do PAPER scalping US500. '
             'Interpretuj WYŁĄCZNIE podane numeryczne zamknięte świece. '
             'Nie twierdź, że oglądałeś zrzut ekranu, widzisz notowania live albo znasz przyszłość. '
             'Oceń trend, warunek potwierdzenia i unieważnienia, koszty, powody WAIT. '
             'Nie wydawaj pewnych komend kupna/sprzedaży. Pisz po polsku.'),
           input='PYTANIE: '+question+'\nDANE WYKRESU: '+json.dumps(payload,ensure_ascii=False))
        return response.output_text or 'Brak odpowiedzi tekstowej z API. Sprawdź limity tokenów.'
    except Exception as ex:
        return f'Nie udało się wywołać AI ({type(ex).__name__}). Analiza regułowa działa niezależnie.'
