"""AUTO-six closed-bar screening: conservative independent hypotheses only."""
from trader import auto_strategy
from trader.strategy import Decision
from trader.visuals import historical_marks
import pandas as pd


def test_auto_two_candidates_still_accepted_after_mtf(monkeypatch):
    def rule(_frame, name, spread):
        side="LONG" if name in auto_strategy.ALL_STRATEGIES[:2] else "WAIT"
        return (Decision(side,name,"synthetic",100,98,104,1.8) if side=="LONG"
                else Decision("WAIT",name,"no setup"))
    monkeypatch.setattr(auto_strategy,"decide_any",rule)
    monkeypatch.setattr(auto_strategy,"filter_mtf_decision",
        lambda decision,snaps,asof:(decision,[]))
    d,rows=auto_strategy.evaluate_auto(pd.DataFrame(),.6,{},use_mtf=True)
    assert d.action=="LONG"
    assert d.strategy==auto_strategy.ALL_STRATEGIES[0]
    assert len(rows)==6
    assert sum(r["Po filtrze MTF"]=="LONG" for r in rows)==2


def test_auto_conflicting_raw_sides_are_wait_even_if_one_vetoed(monkeypatch):
    def rule(frame,name,spread):
        if name==auto_strategy.ALL_STRATEGIES[0]:
            return Decision("LONG",name,"long",100,98,104,1.7)
        if name==auto_strategy.ALL_STRATEGIES[1]:
            return Decision("SHORT",name,"short",100,102,96,1.7)
        return Decision("WAIT",name,"none")
    monkeypatch.setattr(auto_strategy,"decide_any",rule)
    def veto_short(dec,snaps,asof):
        return (Decision("WAIT",dec.strategy,"MTF blocks SHORT") if dec.action=="SHORT" else dec,[])
    monkeypatch.setattr(auto_strategy,"filter_mtf_decision",veto_short)
    d,rows=auto_strategy.evaluate_auto(pd.DataFrame(),.6,use_mtf=True)
    assert d.action=="WAIT" and "Konflikt" in d.reason
    assert len(rows)==6


def test_auto_single_approved_enters_paper_hypothesis_and_mtf_veto_wait(monkeypatch):
    def rule(frame,name,spread):
        return Decision("LONG",name,"synthetic",100,98,104,2) if name==auto_strategy.ALL_STRATEGIES[0] else Decision("WAIT",name,"none")
    monkeypatch.setattr(auto_strategy,"decide_any",rule)
    d,_=auto_strategy.evaluate_auto(pd.DataFrame(),.6,use_mtf=False)
    assert d.action=="LONG" and "1/1" in d.reason
    monkeypatch.setattr(auto_strategy,"filter_mtf_decision",
        lambda d,snaps,asof:(Decision("WAIT",d.strategy,"MTF unavailable"),[]))
    d,_=auto_strategy.evaluate_auto(pd.DataFrame(),.6,use_mtf=True)
    assert d.action=="WAIT" and "0/1" in d.reason


def test_auto_never_uses_a_vetoed_candidate_as_entry(monkeypatch):
    def rule(frame,name,spread):
        if name in auto_strategy.ALL_STRATEGIES[:2]:
            return Decision("LONG",name,"synthetic",100,98,104,1.5)
        return Decision("WAIT",name,"none")
    monkeypatch.setattr(auto_strategy,"decide_any",rule)
    def veto_first(dec,snaps,asof):
        if dec.strategy==auto_strategy.ALL_STRATEGIES[0]:
            return Decision("WAIT",dec.strategy,"blocked"),[]
        return dec,[]
    monkeypatch.setattr(auto_strategy,"filter_mtf_decision",veto_first)
    d,_=auto_strategy.evaluate_auto(pd.DataFrame(),.6,use_mtf=True)
    assert d.action=="LONG" and d.strategy==auto_strategy.ALL_STRATEGIES[1]


def test_historical_auto_marks_is_audit_not_trade(monkeypatch):
    import trader.visuals as visuals
    from trader.auto_strategy import AUTO_MODE
    ix=pd.date_range("2026-11-05T12:01Z",periods=90,freq="min")
    df=pd.DataFrame({"Open":[100.]*90,"High":[101.]*90,"Low":[99.]*90,
                     "Close":[100.]*90,"Spread":[.6]*90},index=ix)
    def only_wait(frame,spread,snapshots=None,asof=None,use_mtf=True):
        return Decision("WAIT",AUTO_MODE,"no consensus"),[]
    monkeypatch.setattr(visuals,"evaluate_auto",only_wait)
    arrows=visuals.historical_marks(df,AUTO_MODE,max_bars=60)
    assert arrows.empty
    assert list(arrows.columns)==["time","action","price","reason"]

def test_counts_one_of_two_then_two_of_three_and_unchanged_conflict_veto(monkeypatch):
    from trader.auto_strategy import vote_summary
    sides = ["LONG", "LONG", "WAIT", "WAIT", "WAIT", "WAIT"]
    veto = {1}
    def rule(frame,name,spread):
        i = auto_strategy.ALL_STRATEGIES.index(name)
        return (Decision(sides[i],name,"controlled",100,
                         98 if sides[i]=="LONG" else 102,
                         103 if sides[i]=="LONG" else 97,2)
                if sides[i] in ("LONG","SHORT") else Decision("WAIT",name,"none"))
    def screen(d,snaps,asof):
        i = auto_strategy.ALL_STRATEGIES.index(d.strategy)
        return (Decision("WAIT",d.strategy,"MTF veto"),[]) if i in veto else (d,[])
    monkeypatch.setattr(auto_strategy,"decide_any",rule)
    monkeypatch.setattr(auto_strategy,"filter_mtf_decision",screen)
    d,rows=auto_strategy.evaluate_auto(pd.DataFrame(),.6,{},use_mtf=True)
    assert d.action=="LONG"
    assert vote_summary(rows)["label"]=="1/2"
    assert "1/2" in d.reason
    assert vote_summary(rows)["approved_names"]==[auto_strategy.ALL_STRATEGIES[0]]
    sides[2] = "LONG"
    veto = {2}
    d,rows=auto_strategy.evaluate_auto(pd.DataFrame(),.6,{},use_mtf=True)
    assert d.action=="LONG" and "2/3" in d.reason
    assert vote_summary(rows)["label"]=="2/3"
    assert len(vote_summary(rows)["approved_names"])==2
    sides[1] = "SHORT"
    d,rows=auto_strategy.evaluate_auto(pd.DataFrame(),.6,{},use_mtf=True)
    assert d.action=="WAIT" and "Konflikt" in d.reason
    assert vote_summary(rows)["conflict"] is True


def test_counts_two_of_two_and_no_signal(monkeypatch):
    from trader.auto_strategy import vote_summary
    def synthetic(frame,name,spread):
        if name in auto_strategy.ALL_STRATEGIES[:2]:
            return Decision("LONG",name,"OK",100,98,105,2)
        return Decision("WAIT",name,"NO")
    monkeypatch.setattr(auto_strategy,"decide_any",synthetic)
    d,rows=auto_strategy.evaluate_auto(pd.DataFrame(),.5,use_mtf=False)
    assert d.action=="LONG" and vote_summary(rows)["label"]=="2/2"
    monkeypatch.setattr(auto_strategy,"decide_any",
        lambda frame,name,spread: Decision("WAIT",name,"no setup"))
    d,rows=auto_strategy.evaluate_auto(pd.DataFrame(),.5,use_mtf=False)
    assert d.action=="WAIT" and vote_summary(rows)["label"]=="0/0"
