-- Extra Lahore departments the jurisdiction knowledge base can route to. VERIFY before a pilot.
insert into authorities (authority_id, city, name, categories, filing_channel, filing_target, helpline, benchmark_days) values
 ('MCL-LIGHTS', 'Lahore', 'MCL Street Lighting',          '{electrical}',                      'written_application', 'Metropolitan Corporation Lahore, Street Lighting', null, 10),
 ('LDA',        'Lahore', 'Lahore Development Authority', '{roads,other}',                     'written_application', 'LDA, Engineering Wing (scheme maintenance)',        null, 14),
 ('TEPA',       'Lahore', 'TEPA (Traffic Engineering)',   '{roads}',                           'written_application', 'TEPA, Lahore Development Authority',               null, 14),
 ('PHA',        'Lahore', 'Parks & Horticulture Authority','{other}',                          'written_application', 'PHA Lahore',                                       null, 10),
 ('LCB',        'Lahore', 'Lahore Cantonment Board',      '{roads,water,sanitation,electrical,encroachment,other}', 'written_application', 'Lahore Cantonment Board', null, 14)
on conflict (authority_id) do nothing;
