import 'package:flutter/material.dart';

import '../gateway/models.dart';
import 'memory_labels.dart';

/// A grouped evidence section with one card per graph node or raw chunk.
final class EvidenceCards extends StatefulWidget {
  const EvidenceCards({
    super.key,
    required this.evidence,
    this.onOpenGraphNode,
    this.onOpenGraph,
  });

  final List<EvidenceItem> evidence;

  /// Opens a graph evidence item in the current Explore workspace.
  ///
  /// Raw evidence never receives this callback. The caller owns the source
  /// Brain selection, so snapshot links cannot follow the active Brain by
  /// accident.
  final ValueChanged<GraphNode>? onOpenGraphNode;
  final ValueChanged<GraphNode>? onOpenGraph;

  @override
  State<EvidenceCards> createState() => _EvidenceCardsState();
}

final class _EvidenceCardsState extends State<EvidenceCards> {
  bool _expanded = true;

  @override
  Widget build(BuildContext context) {
    if (widget.evidence.isEmpty) return const SizedBox.shrink();
    final nodes = <String, GraphNode>{
      for (final item in widget.evidence.whereType<GraphNodeEvidence>())
        item.node.id: item.node,
    };
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        const Divider(height: 28),
        TextButton.icon(
          onPressed: () => setState(() => _expanded = !_expanded),
          icon: Icon(_expanded ? Icons.expand_less : Icons.expand_more),
          label: const Text('Evidence'),
          style: TextButton.styleFrom(
            alignment: Alignment.centerLeft,
            padding: const EdgeInsets.symmetric(vertical: 12),
          ),
        ),
        if (_expanded)
          ...widget.evidence.map(
            (item) => Padding(
              padding: const EdgeInsets.only(bottom: 12),
              child: _EvidenceCard(
                item: item,
                nodes: nodes,
                onOpenGraphNode: widget.onOpenGraphNode ?? widget.onOpenGraph,
              ),
            ),
          ),
      ],
    );
  }
}

final class _EvidenceCard extends StatelessWidget {
  const _EvidenceCard({
    required this.item,
    required this.nodes,
    this.onOpenGraphNode,
  });

  final EvidenceItem item;
  final Map<String, GraphNode> nodes;
  final ValueChanged<GraphNode>? onOpenGraphNode;

  @override
  Widget build(BuildContext context) {
    return Card(
      margin: EdgeInsets.zero,
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: switch (item) {
          GraphNodeEvidence evidence => _GraphCard(
              evidence: evidence,
              nodes: nodes,
              onOpenGraphNode: onOpenGraphNode,
            ),
          UnprocessedEvidence evidence => _ChunkCard(evidence: evidence),
        },
      ),
    );
  }
}

final class _GraphCard extends StatelessWidget {
  const _GraphCard({
    required this.evidence,
    required this.nodes,
    this.onOpenGraphNode,
  });

  final GraphNodeEvidence evidence;
  final Map<String, GraphNode> nodes;
  final ValueChanged<GraphNode>? onOpenGraphNode;

  @override
  Widget build(BuildContext context) {
    final node = evidence.node;
    final title = memoryTitle(node);
    final description = _nodeDescription(node, title);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Align(
          alignment: Alignment.centerLeft,
          child: Chip(label: Text(memoryKind(node))),
        ),
        const SizedBox(height: 4),
        Text(title, style: Theme.of(context).textTheme.titleMedium),
        if (description.isNotEmpty) ...[
          const SizedBox(height: 4),
          Text(description),
        ],
        if (evidence.links.isNotEmpty) ...[
          const Divider(height: 24),
          ...evidence.links.map((link) => _LinkRow(link: link, nodes: nodes)),
        ],
        if (onOpenGraphNode != null) ...[
          const SizedBox(height: 8),
          Align(
            alignment: Alignment.centerLeft,
            child: OutlinedButton.icon(
              onPressed: () => onOpenGraphNode!(node),
              icon: const Icon(Icons.account_tree_outlined, size: 18),
              label: const Text('Explore current graph'),
            ),
          ),
        ],
      ],
    );
  }
}

final class _LinkRow extends StatelessWidget {
  const _LinkRow({required this.link, required this.nodes});

  final LinkedEdge link;
  final Map<String, GraphNode> nodes;

  @override
  Widget build(BuildContext context) {
    final from = nodes[link.from];
    final to = nodes[link.to];
    final fromTitle = connectedMemoryTitle(from);
    final toTitle = connectedMemoryTitle(to);
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(
            Icons.arrow_forward,
            size: 18,
            color: Theme.of(context).colorScheme.primary,
          ),
          const SizedBox(width: 8),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text('${relationshipTitle(link)}: $fromTitle → $toTitle'),
                if (link.context?.trim().isNotEmpty == true)
                  Text(
                    link.context!,
                    style: Theme.of(context).textTheme.bodySmall,
                  ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

final class _ChunkCard extends StatelessWidget {
  const _ChunkCard({required this.evidence});

  final UnprocessedEvidence evidence;

  @override
  Widget build(BuildContext context) {
    final chunk = evidence.chunk;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        const Align(
          alignment: Alignment.centerLeft,
          child: Chip(
            avatar: Icon(Icons.pending_outlined, size: 16),
            label: Text('Unprocessed'),
          ),
        ),
        const SizedBox(height: 4),
        Text(chunk.content),
        const SizedBox(height: 10),
        Text(
          '${chunk.source} · chunk ${chunk.chunkPosition + 1} of ${chunk.totalChunks}',
          style: Theme.of(context).textTheme.bodySmall,
        ),
        if (chunk.hints.isNotEmpty)
          Text(
            'Hints: ${chunk.hints.join(', ')}',
            style: Theme.of(context).textTheme.bodySmall,
          ),
      ],
    );
  }
}

String _nodeDescription(GraphNode node, String title) {
  final value = node.description ?? node.content ?? node.summary ?? '';
  return value == title ? '' : value;
}
