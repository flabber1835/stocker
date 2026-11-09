"""Pure display follow-up retains every installed source and financial witness."""
from sentinel import url_selected_source_basis as basis,runtime_admission as admission

def test_only_presentational_modules_and_exact_source_checker_change():
    profile=basis._profile()
    assert basis.PANEL_PRESENTATION_PREDECESSOR_REVISION=='a0a82c6ad9211fdcf9fdad9faa801b8af65239ea'
    prior=profile['retained_predecessors'][basis.PANEL_PRESENTATION_PREDECESSOR_REVISION]['files']
    actual=profile['retained_predecessors'][basis.STARTUP_PROFILE_PREDECESSOR_REVISION]['files']
    assert len(prior)==len(actual)==463
    assert admission.source_closure(prior)=='9385294419b070cf3955f0cc3eb3370442883f8113b8cc4dd8f5b64beece4d4f'
    assert {name for name in prior if prior[name]!=actual[name]}=={'panel/render.py','panel/styles.py','url_selected_source_basis.py'}
    assert profile['authority_effect']=='NONE'
    assert basis.predecessor_view(admission._source_files(basis.PROFILE.parent),previous=prior)==prior
