import 'package:flutter/material.dart';

import '../explore/explore_controller.dart';
import '../gateway/models.dart';
import '../persistence/models.dart';

/// Detail view for one selected Explore node.
///
/// The detail route shares the controller with the canvas. Selecting or
/// following an edge therefore updates both views without copying graph state.
final class GraphNodeDetailScreen extends StatefulWidget {
  const GraphNodeDetailScreen({
    super.key,
    this.controller,
    this.workspaceController,
    this.nodeId,
    this.recordId,
    this.selectedNodeId,
    this.node,
    this.connections,
    this.onBackToMap,
    this.onNodeSelected,
  });

  final ExploreWorkspaceController? controller;
  final ExploreWorkspaceController? workspaceController;
  final String? nodeId;
  final String? recordId;
  final String? selectedNodeId;
  final GraphNode? node;
  final List<GraphConnection>? connections;
  final VoidCallback? onBackToMap;
  final ValueChanged<String>? onNodeSelected;

  @override
  State<GraphNodeDetailScreen> createState() => _GraphNodeDetailScreenState();
}

final class _GraphNodeDetailScreenState extends State<GraphNodeDetailScreen> {
  Object? _failure;
  bool _following = false;

  @override
  void initState() {
    super.initState();
    final controller = widget.controller ?? widget.workspaceController;
    final id = widget.nodeId ??
        widget.recordId ??
        widget.selectedNodeId ??
        widget.node?.id;
    if (controller != null && id != null) controller.selectNode(id);
  }

  @override
  Widget build(BuildContext context) {
    final controller = widget.controller ?? widget.workspaceController;
    final projection = controller?.state;
    final id = widget.nodeId ??
        widget.recordId ??
        widget.selectedNodeId ??
        projection?.selectedNodeId ??
        widget.node?.id;
    final item = id == null
        ? null
        : projection?.nodes.cast<WorkspaceNode?>().firstWhere(
              (candidate) => candidate?.node.id == id,
              orElse: () => null,
            );
    final node = item?.node ?? widget.node;
    if (node == null) {
      return Scaffold(
        appBar: AppBar(
          leading: _backButton(context),
          title: const Text('Memory'),
        ),
        body: const Center(child: Text('This memory is not loaded.')),
      );
    }

    final edges = projection?.edges
            .where(
                (edge) => edge.edge.from == node.id || edge.edge.to == node.id)
            .toList(growable: false) ??
        widget.connections
            ?.map((connection) => WorkspaceEdge(
                  edge: connection.edge,
                  status: WorkspaceItemStatus.loaded,
                ))
            .where(
                (edge) => edge.edge.from == node.id || edge.edge.to == node.id)
            .toList(growable: false) ??
        const <WorkspaceEdge>[];
    return Scaffold(
      appBar: AppBar(
        leading: _backButton(context),
        title: const Text('Memory'),
        actions: [
          if (controller != null)
            IconButton(
              onPressed: _refreshNode,
              tooltip: 'Refresh memory',
              icon: const Icon(Icons.refresh),
            ),
        ],
      ),
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.fromLTRB(20, 12, 20, 28),
          children: [
            Align(
              alignment: Alignment.centerLeft,
              child: TextButton.icon(
                onPressed: widget.onBackToMap ??
                    () => Navigator.of(context).maybePop(),
                icon: const Icon(Icons.arrow_back, size: 18),
                label: const Text('Back to map'),
              ),
            ),
            if (_failure != null) ...[
              _Notice(message: _messageFor(_failure)),
              const SizedBox(height: 12),
            ],
            _NodeHeader(item: item, node: node),
            const SizedBox(height: 18),
            if (_description(node).isNotEmpty) ...[
              Text(_description(node)),
              const SizedBox(height: 18),
            ],
            Text(
              'Connections',
              style: Theme.of(context).textTheme.titleMedium,
            ),
            const SizedBox(height: 8),
            if (edges.isEmpty)
              const Text('No connections loaded.')
            else
              ...edges.map((edge) => _ConnectionTile(
                    item: edge,
                    selectedNodeId: node.id,
                    following: _following,
                    onTap: () => _follow(edge),
                  )),
          ],
        ),
      ),
    );
  }

  Widget _backButton(BuildContext context) {
    return IconButton(
      onPressed: widget.onBackToMap ?? () => Navigator.of(context).maybePop(),
      tooltip: 'Back to map',
      icon: const Icon(Icons.arrow_back),
    );
  }

  Future<void> _refreshNode() async {
    final controller = widget.controller ?? widget.workspaceController;
    final id = widget.nodeId ??
        widget.recordId ??
        widget.selectedNodeId ??
        controller?.state.selectedNodeId;
    if (controller == null || id == null) return;
    setState(() => _failure = null);
    try {
      await controller.openNode(id);
      if (mounted) setState(() {});
    } on Object catch (error) {
      if (mounted) setState(() => _failure = error);
    }
  }

  Future<void> _follow(WorkspaceEdge item) async {
    final controller = widget.controller ?? widget.workspaceController;
    if (controller == null || item.status == WorkspaceItemStatus.missing) {
      if (item.status == WorkspaceItemStatus.missing && mounted) {
        setState(
            () => _failure = StateError('This connection no longer exists.'));
      }
      return;
    }
    setState(() {
      _following = true;
      _failure = null;
    });
    try {
      await controller.followEdge(item.edge.id);
      final selected = controller.state.selectedNodeId;
      if (mounted) {
        setState(() => _following = false);
        if (selected != null) widget.onNodeSelected?.call(selected);
      }
    } on Object catch (error) {
      if (mounted) {
        setState(() {
          _following = false;
          _failure = error;
        });
      }
    }
  }

  String _description(GraphNode node) {
    final value = node.description ?? node.content ?? node.summary ?? '';
    return value.trim();
  }

  String _messageFor(Object? error) {
    return error is StateError ? error.message : 'Could not load this memory.';
  }
}

final class _NodeHeader extends StatelessWidget {
  const _NodeHeader({required this.item, required this.node});

  final WorkspaceNode? item;
  final GraphNode node;

  @override
  Widget build(BuildContext context) {
    final status = item?.status;
    final missing = status == WorkspaceItemStatus.missing;
    final isNew = status == WorkspaceItemStatus.newItem;
    return Opacity(
      opacity: missing ? .48 : 1,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Wrap(
            spacing: 8,
            runSpacing: 6,
            crossAxisAlignment: WrapCrossAlignment.center,
            children: [
              Chip(label: Text(node.table)),
              if (missing) const Chip(label: Text('Missing')),
              if (isNew) const Chip(label: Text('New')),
            ],
          ),
          const SizedBox(height: 4),
          Text(
            _nodeTitle(node),
            style: Theme.of(context).textTheme.headlineSmall,
          ),
          const SizedBox(height: 4),
          SelectableText(
            node.id,
            style: Theme.of(context).textTheme.bodySmall,
          ),
          if (missing) ...[
            const SizedBox(height: 12),
            const _Notice(
                message:
                    'This memory was reported missing. Showing cached data.'),
          ],
        ],
      ),
    );
  }
}

final class _ConnectionTile extends StatelessWidget {
  const _ConnectionTile({
    required this.item,
    required this.selectedNodeId,
    required this.following,
    required this.onTap,
  });

  final WorkspaceEdge item;
  final String selectedNodeId;
  final bool following;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final edge = item.edge;
    final outgoing = edge.from == selectedNodeId;
    final target = outgoing ? edge.to : edge.from;
    final missing = item.status == WorkspaceItemStatus.missing;
    final isNew = item.status == WorkspaceItemStatus.newItem;
    final label = edge.context?.trim().isNotEmpty == true
        ? edge.context!.trim()
        : edge.table;
    return Opacity(
      opacity: missing ? .45 : 1,
      child: Card(
        margin: const EdgeInsets.symmetric(vertical: 4),
        child: ListTile(
          enabled: !missing && !following,
          leading: Icon(outgoing ? Icons.arrow_forward : Icons.arrow_back),
          title: Text('$label → $target'),
          subtitle: Text(
            '${edge.from} → ${edge.to}${isNew ? ' · New' : ''}${missing ? ' · Missing' : ''}',
          ),
          trailing: following
              ? const SizedBox(
                  width: 20,
                  height: 20,
                  child: CircularProgressIndicator(strokeWidth: 2),
                )
              : const Icon(Icons.chevron_right),
          onTap: onTap,
        ),
      ),
    );
  }
}

final class _Notice extends StatelessWidget {
  const _Notice({required this.message});

  final String message;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: Theme.of(context).colorScheme.surfaceContainerHighest,
        borderRadius: BorderRadius.circular(12),
      ),
      child: Text(message),
    );
  }
}

String _nodeTitle(GraphNode node) {
  if (node.name?.trim().isNotEmpty == true) return node.name!.trim();
  if (node.summary?.trim().isNotEmpty == true) return node.summary!.trim();
  if (node.content?.trim().isNotEmpty == true) {
    final first = node.content!.split(RegExp(r'[.!?]')).first.trim();
    if (first.isNotEmpty) return first;
  }
  return node.id;
}
