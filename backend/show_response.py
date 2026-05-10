import json

data = json.load(open('debug_response.json', encoding='utf-8'))

h = data['history']
print('=== HOME LAST 10 ===')
for m in h['home_last10']:
    d = m.get('match_date', '?')
    ht = m.get('home_team_name', '?')
    at = m.get('away_team_name', '?')
    hs = m.get('home_score', '-')
    aws = m.get('away_score', '-')
    lg = m.get('league_name', '')
    print('  ' + str(d) + ' | ' + str(ht) + ' ' + str(hs) + '-' + str(aws) + ' ' + str(at) + ' (' + str(lg) + ')')

print()
print('=== AWAY LAST 10 ===')
for m in h['away_last10']:
    d = m.get('match_date', '?')
    ht = m.get('home_team_name', '?')
    at = m.get('away_team_name', '?')
    hs = m.get('home_score', '-')
    aws = m.get('away_score', '-')
    lg = m.get('league_name', '')
    print('  ' + str(d) + ' | ' + str(ht) + ' ' + str(hs) + '-' + str(aws) + ' ' + str(at) + ' (' + str(lg) + ')')

print()
print('=== H2H ===')
for m in h['h2h']:
    d = m.get('match_date', '?')
    ht = m.get('home_team_name', '?')
    at = m.get('away_team_name', '?')
    hs = m.get('home_score', '-')
    aws = m.get('away_score', '-')
    lg = m.get('league_name', '')
    print('  ' + str(d) + ' | ' + str(ht) + ' ' + str(hs) + '-' + str(aws) + ' ' + str(at) + ' (' + str(lg) + ')')

print()
print('=== AI CONTEXT ===')
ai = data.get('ai_context', {})
print('Enabled: ' + str(ai.get('enabled')))
print('Stats sources: ' + str(ai.get('statistics_sources')))

home_ctx = ai.get('home_last10', {})
print('Home sample_count: ' + str(home_ctx.get('sample_count')))
print('Home stats_available: ' + str(home_ctx.get('stats_available_count')))

home_form = home_ctx.get('form', {})
print('Home form: W' + str(home_form.get('wins')) + '/D' + str(home_form.get('draws')) + '/L' + str(home_form.get('losses')) + ' WR:' + str(home_form.get('win_rate')) + '%')

# Check per-match detailed stats in ai_context
matches = home_ctx.get('matches', [])
if matches:
    print()
    print('=== PER-MATCH STATS (first 2) ===')
    for idx, m in enumerate(matches[:2]):
        print('Match ' + str(idx+1) + ': ' + str(m.get('match_date')) + ' | ' + str(m.get('home_team_name')) + ' ' + str(m.get('home_score')) + '-' + str(m.get('away_score')) + ' ' + str(m.get('away_team_name')))
        print('  stats_available: ' + str(m.get('stats_available')))
        print('  result: ' + str(m.get('result')))
        stats = m.get('statistics', [])
        if stats:
            print('  HAS INLINE STATISTICS: ' + str(len(stats)) + ' period(s)')
            for p in stats[:1]:
                for g in p.get('groups', [])[:2]:
                    print('    ' + str(g.get('group_name')) + ':')
                    for item in g.get('items', [])[:4]:
                        print('      ' + str(item.get('name')) + ': H=' + str(item.get('home')) + ' A=' + str(item.get('away')))
        else:
            print('  NO inline statistics')
        pm = m.get('period_metrics', {})
        if pm:
            print('  period_metrics periods: ' + str(list(pm.keys())))
else:
    print('No matches in ai_context!')
