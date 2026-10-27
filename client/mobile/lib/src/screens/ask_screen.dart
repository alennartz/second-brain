import 'package:flutter/material.dart';

import '../gateway/brain_gateway.dart';
import '../widgets/app_logo.dart';

/// The one-shot Ask composer. The controller remains alive while its result route is open.
final class AskScreen extends StatefulWidget {
  const AskScreen({
    super.key,
    required this.gateway,
    required this.onOpenSettings,
    required this.onAsk,
  });

  final BrainGateway gateway;
  final VoidCallback onOpenSettings;
  final ValueChanged<String> onAsk;

  @override
  State<AskScreen> createState() => _AskScreenState();
}

final class _AskScreenState extends State<AskScreen> {
  late final TextEditingController _controller;

  @override
  void initState() {
    super.initState();
    _controller = TextEditingController();
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final hasQuestion = _controller.text.trim().isNotEmpty;
    return Column(
      children: [
        AppBar(
          leading: const Padding(
            padding: EdgeInsets.all(8),
            child: AppLogo(size: 40),
          ),
          title: const Text('Ask'),
          actions: [
            IconButton(
              onPressed: widget.onOpenSettings,
              tooltip: 'Settings',
              icon: const Icon(Icons.settings_outlined),
            ),
          ],
        ),
        Expanded(
          child: SafeArea(
            top: false,
            child: SingleChildScrollView(
              padding: const EdgeInsets.fromLTRB(20, 8, 20, 20),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  TextField(
                    controller: _controller,
                    minLines: 3,
                    maxLines: 8,
                    keyboardType: TextInputType.multiline,
                    textInputAction: TextInputAction.newline,
                    decoration: const InputDecoration(
                      hintText: 'Ask your memory a question',
                      border: OutlineInputBorder(),
                      alignLabelWithHint: true,
                    ),
                    onChanged: (_) => setState(() {}),
                  ),
                  if (!hasQuestion) ...[
                    const SizedBox(height: 20),
                    Text(
                      'Try asking',
                      style: Theme.of(context).textTheme.labelLarge,
                    ),
                    const SizedBox(height: 8),
                    _QuestionSuggestion(
                      question: 'What did I decide about the garden layout?',
                      onTap: _setQuestion,
                    ),
                    const SizedBox(height: 8),
                    _QuestionSuggestion(
                      question: 'What do I know about sailing?',
                      onTap: _setQuestion,
                    ),
                  ],
                ],
              ),
            ),
          ),
        ),
        SafeArea(
          top: false,
          child: Padding(
            padding: const EdgeInsets.fromLTRB(16, 12, 16, 16),
            child: SizedBox(
              width: double.infinity,
              child: ElevatedButton(
                onPressed: hasQuestion ? _submitQuestion : null,
                child: const Text('Ask'),
              ),
            ),
          ),
        ),
      ],
    );
  }

  void _setQuestion(String question) {
    _controller
      ..text = question
      ..selection = TextSelection.collapsed(offset: question.length);
    setState(() {});
  }

  void _submitQuestion() {
    final question = _controller.text.trim();
    if (question.isEmpty) return;
    widget.onAsk(question);
  }
}

final class _QuestionSuggestion extends StatelessWidget {
  const _QuestionSuggestion({required this.question, required this.onTap});

  final String question;
  final ValueChanged<String> onTap;

  @override
  Widget build(BuildContext context) {
    return OutlinedButton.icon(
      onPressed: () => onTap(question),
      icon: const Icon(Icons.search, size: 18),
      label: Align(
        alignment: Alignment.centerLeft,
        child: Text(question),
      ),
      style: OutlinedButton.styleFrom(
        alignment: Alignment.centerLeft,
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
      ),
    );
  }
}
