import plotly.graph_objects as go
from trader.paper_display import annotate_open_paper

def test_never_show_entry_sl_tp_without_open_position():
    for p in (None,{},{"status":"PENDING","entry_mid":100,"stop_mid":98,"target_mid":102},
              {"status":"CLOSED_TP","entry_mid":100,"stop_mid":98,"target_mid":102}):
        fig=annotate_open_paper(go.Figure(),p)
        assert len(fig.layout.shapes)==0
        assert len(fig.layout.annotations)==0

def test_active_position_levels_always_exact():
    p={"status":"OPEN","trade_id":"abc1234567","entry_mid":100,
       "entry_executable":100.55,"stop_mid":98,"target_mid":102}
    f=annotate_open_paper(go.Figure(),p)
    assert len(f.layout.shapes)==4
    assert {float(x.y0) for x in f.layout.shapes}=={98,100,100.55,102}
    notes=[x.text for x in f.layout.annotations]
    assert any("PAPER ENTRY" in x for x in notes)
    assert any("PAPER FILL BID/ASK" in x for x in notes)
    assert any("PAPER SL" in x for x in notes)
    assert any("PAPER TP" in x for x in notes)
    assert all("abc12345" in x for x in notes)
