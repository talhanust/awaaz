-- Lahore authorities. VERIFY every channel, target and helpline before a real pilot.
insert into authorities (authority_id, city, name, categories, filing_channel, filing_target, helpline, benchmark_days, escalation_contacts) values
 ('LESCO',        'Lahore', 'LESCO',                 '{electrical}',        'portal',              'LESCO online complaint portal',                        '118',  7,  '{}'),
 ('WASA-LHR',     'Lahore', 'WASA Lahore',           '{water,sanitation}',  'email',               'complaints@wasa-lahore.example',                        null,   7,  '{}'),
 ('LWMC',         'Lahore', 'LWMC',                  '{sanitation}',        'whatsapp',            'LWMC WhatsApp complaint line',                          null,   3,  '{}'),
 ('MCL-ROADS',    'Lahore', 'MCL Roads',             '{roads}',             'written_application', 'Metropolitan Corporation Lahore, Roads Wing',           null,   14, '{"J Block":{"title":"UC Chairman, Johar Town J Block (demo contact)","email":"uc-jblock@example.pk"}}'),
 ('SNGPL',        'Lahore', 'SNGPL',                 '{gas}',               'portal',              'SNGPL online complaint portal',                        '1199', 5,  '{}'),
 ('MCL-ENC',      'Lahore', 'MCL Anti-Encroachment', '{encroachment}',      'written_application', 'Metropolitan Corporation Lahore, Anti-Encroachment Cell', null, 21, '{}');

-- Demo citizens (fake numbers) so seeded Issues have reporters.
insert into citizens (citizen_hash, phone) values
 ('seed-citizen-01', '+920000000001'), ('seed-citizen-02', '+920000000002'), ('seed-citizen-03', '+920000000003');

-- Demo Issues around Johar Town (coordinates are illustrative).
insert into issues (issue_id, city, sector, category, severity, authority_id, summary, geo_private, report_count, confirmations,
                    tracker_hash, status, escalation_tier, first_reported_at, expected_by) values
 ('AWZ-LHR-00231','Lahore','J Block','roads','high','MCL-ROADS','Deep pothole on the main road outside J Block market',
   st_setsrid(st_makepoint(74.27277, 31.47011),4326)::geography, 12, 4, 'seed-citizen-01','open',0, now()-interval '9 days', now()+interval '5 days'),
 ('AWZ-LHR-00219','Lahore','L Block','sanitation','high','WASA-LHR','Sewage overflowing in street 14, L Block',
   st_setsrid(st_makepoint(74.26693, 31.46862),4326)::geography, 6, 3, 'seed-citizen-02','escalated_t1',1, now()-interval '19 days', now()-interval '5 days'),
 ('AWZ-LHR-00226','Lahore','K Block','electrical','urgent','LESCO','Sparking wires on a pole near K Block park',
   st_setsrid(st_makepoint(74.27904, 31.47240),4326)::geography, 5, 2, 'seed-citizen-03','acknowledged',0, now()-interval '13 days', now()-interval '6 days'),
 ('AWZ-LHR-00245','Lahore','J Block','roads','medium','MCL-ROADS','Broken speed breaker in J Block',
   st_setsrid(st_makepoint(74.27178, 31.46790),4326)::geography, 2, 1, 'seed-citizen-02','open',0, now()-interval '4 days', now()+interval '10 days'),
 ('AWZ-LHR-00247','Lahore','J Block','roads','low','MCL-ROADS','Small pothole on J Block street 3',
   st_setsrid(st_makepoint(74.27331, 31.46646),4326)::geography, 1, 0, 'seed-citizen-03','open',0, now()-interval '2 days', now()+interval '12 days');

insert into reports (report_id, issue_id, citizen_hash, input_type, raw_text, geo_private)
select 'R-' || issue_id || '-1', issue_id, tracker_hash, 'text', summary, geo_private from issues;

insert into events (issue_id, type, actor, created_at)
select issue_id, 'filed', tracker_hash, first_reported_at from issues;

select setval('issue_seq', 1300);
