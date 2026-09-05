from pathlib import Path

agent = Path('app/src/main/kotlin/ai/closepaw/app/AgentService.kt')
text = agent.read_text(encoding='utf-8')

old_reuse = '''        val current = session
        val reusableHandsFreeSession = current != null &&
            current.state.value != SessionState.Shutdown &&
            current.getServices().config.approvalMode == ApprovalMode.AUTO_APPROVE &&
            current.getServices().config.traceEnabled
'''
new_reuse = '''        val current = session
        val desiredHandsFreeModel =
            ai.closepaw.ui.capsule.voice.HandsFreeIntentGate.activeApiFallbackModel()
                ?: AppSettingsStore(this).load().selectedModel
        val reusableHandsFreeSession = current != null &&
            current.state.value != SessionState.Shutdown &&
            current.getServices().config.approvalMode == ApprovalMode.AUTO_APPROVE &&
            current.getServices().config.traceEnabled &&
            current.effectiveMainModel() == desiredHandsFreeModel
'''
if old_reuse not in text:
    raise SystemExit('hands-free reusable-session anchor not found')
text = text.replace(old_reuse, new_reuse, 1)

old_model = '                                mainModel = settings.selectedModel,\n'
new_model = '''                                mainModel = if (handsFree) {
                                    ai.closepaw.ui.capsule.voice.HandsFreeIntentGate.activeApiFallbackModel()
                                        ?: settings.selectedModel
                                } else settings.selectedModel,
'''
if old_model not in text:
    raise SystemExit('SessionConfig mainModel anchor not found')
text = text.replace(old_model, new_model, 1)

old_log = '''                "starting fresh hands-free session: auto-approve=true trace=true",
'''
new_log = '''                "starting fresh hands-free session: model=$desiredHandsFreeModel auto-approve=true trace=true",
'''
if old_log not in text:
    raise SystemExit('hands-free fresh-session relay anchor not found')
text = text.replace(old_log, new_log, 1)

agent.write_text(text, encoding='utf-8')
print('Hands-free API fallback execution routing applied')
