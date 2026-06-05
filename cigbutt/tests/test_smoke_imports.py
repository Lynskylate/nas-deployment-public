from cigbutt import ProviderRouter, build_parser, run_analysis, run_e2e, run_hk_scan, run_market_scan


def test_imports_smoke() -> None:
    assert callable(run_analysis)
    assert callable(run_e2e)
    assert callable(run_hk_scan)
    assert callable(run_market_scan)
    assert isinstance(ProviderRouter(), ProviderRouter)
    parser = build_parser()
    assert parser.prog
