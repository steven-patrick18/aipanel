import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useFormContext } from "react-hook-form";
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  Handle,
  Position,
  addEdge,
  applyEdgeChanges,
  applyNodeChanges,
  type Connection,
  type Edge,
  type Node,
  type NodeProps,
  type NodeTypes,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { Code, Plus, Trash2, X } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import type { AgentCreateInput } from "@/lib/validation";

/* ========================================================================
 * Data shapes
 * ======================================================================*/

type TriggerKind =
  | "call_start"
  | "intent_detected"
  | "objection_raised"
  | "silence_5s"
  | "user_request_human";

type ConditionOp = "equals" | "contains" | "exists" | "gt" | "lt";

type TriggerData = {
  kind: "trigger";
  trigger: TriggerKind;
  intent?: string;
  [key: string]: unknown;
};

type ConditionData = {
  kind: "condition";
  field: string;
  op: ConditionOp;
  value: string;
  [key: string]: unknown;
};

type ActionKind =
  | "say"
  | "transfer"
  | "dispose"
  | "set_var"
  | "kb_lookup"
  | "schedule_callback";

type ActionData = {
  kind: "action";
  action: ActionKind;
  // Free-form params per action type — kept loose to match worker tools.
  params: Record<string, string>;
  [key: string]: unknown;
};

type NodeData = TriggerData | ConditionData | ActionData;
type FlowNode = Node<NodeData>;

interface ScenarioTree {
  rules: unknown[];                       // compiled output for the worker
  graph?: { nodes: FlowNode[]; edges: Edge[] }; // raw editor state
}

const TRIGGER_LABELS: Record<TriggerKind, string> = {
  call_start: "Call start",
  intent_detected: "Intent detected",
  objection_raised: "Objection raised",
  silence_5s: "Silence > 5 s",
  user_request_human: "User asks for human",
};

const ACTION_LABELS: Record<ActionKind, string> = {
  say: "Say (TTS line)",
  transfer: "Transfer to ingroup",
  dispose: "Dispose call",
  set_var: "Set variable",
  kb_lookup: "Knowledge-base lookup",
  schedule_callback: "Schedule callback",
};

const ACTION_PARAM_HINTS: Record<ActionKind, { key: string; label: string }[]> = {
  say:               [{ key: "text",     label: "What to say" }],
  transfer:          [{ key: "ingroup",  label: "Ingroup ID" }, { key: "summary", label: "Summary" }],
  dispose:           [{ key: "status",   label: "Disposition code" }, { key: "notes", label: "Notes" }],
  set_var:           [{ key: "name",     label: "Variable name" }, { key: "value", label: "Value" }],
  kb_lookup:         [{ key: "query",    label: "Search query (templated)" }],
  schedule_callback: [{ key: "when",     label: "ISO datetime" },   { key: "notes", label: "Notes" }],
};

/* ========================================================================
 * Custom nodes
 * ======================================================================*/

function NodeShell({
  tone, title, subtitle, children,
}: {
  tone: "indigo" | "amber" | "emerald";
  title: string;
  subtitle?: string;
  children?: React.ReactNode;
}) {
  const cls = {
    indigo:  "bg-indigo-50  border-indigo-300  text-indigo-900",
    amber:   "bg-amber-50   border-amber-300   text-amber-900",
    emerald: "bg-emerald-50 border-emerald-300 text-emerald-900",
  }[tone];
  return (
    <div className={`min-w-[180px] rounded-md border ${cls} px-3 py-2 shadow-sm`}>
      <div className="text-[10px] uppercase tracking-wide opacity-70">{title}</div>
      {subtitle && <div className="text-sm font-medium">{subtitle}</div>}
      {children}
    </div>
  );
}

function TriggerNode({ data }: NodeProps<FlowNode>) {
  const d = data as TriggerData;
  const sub = d.trigger === "intent_detected" && d.intent
    ? `intent = "${d.intent}"`
    : TRIGGER_LABELS[d.trigger];
  return (
    <>
      <NodeShell tone="indigo" title="Trigger" subtitle={sub} />
      <Handle type="source" position={Position.Right} />
    </>
  );
}

function ConditionNode({ data }: NodeProps<FlowNode>) {
  const d = data as ConditionData;
  return (
    <>
      <Handle type="target" position={Position.Left} />
      <NodeShell
        tone="amber"
        title="Condition"
        subtitle={`${d.field || "field"} ${d.op} ${d.op === "exists" ? "" : `"${d.value}"`}`}
      />
      <Handle type="source" position={Position.Right} id="yes" style={{ top: "30%" }} />
      <Handle type="source" position={Position.Right} id="no"  style={{ top: "70%" }} />
    </>
  );
}

function ActionNode({ data }: NodeProps<FlowNode>) {
  const d = data as ActionData;
  const summary = Object.entries(d.params || {})
    .filter(([, v]) => v)
    .map(([k, v]) => `${k}=${v}`)
    .join(", ");
  return (
    <>
      <Handle type="target" position={Position.Left} />
      <NodeShell
        tone="emerald"
        title="Action"
        subtitle={ACTION_LABELS[d.action]}
      >
        {summary && <div className="text-[11px] opacity-80 mt-0.5 line-clamp-2">{summary}</div>}
      </NodeShell>
    </>
  );
}

const NODE_TYPES: NodeTypes = {
  trigger: TriggerNode,
  condition: ConditionNode,
  action: ActionNode,
};

/* ========================================================================
 * Compile graph → LLM tool/rule list
 * ======================================================================*/

function compileGraph(nodes: FlowNode[], edges: Edge[]) {
  // For each trigger node, walk the graph forward and emit a rule:
  //   { when: <trigger>, do: [<actions>], conditions: [...] }
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const out: any[] = [];

  function walk(nodeId: string, path: any[], conditions: any[], handle?: string | null) {
    const n = byId.get(nodeId);
    if (!n) return;
    if (n.type === "condition") {
      const c = n.data as ConditionData;
      // Branch on each outgoing edge using its sourceHandle (yes/no).
      const outs = edges.filter((e) => e.source === nodeId);
      for (const e of outs) {
        const branch = e.sourceHandle === "no"
          ? { ...c, op: invert(c.op) }
          : c;
        walk(e.target, path, [...conditions, branch], e.sourceHandle ?? null);
      }
    } else if (n.type === "action") {
      const a = n.data as ActionData;
      path.push({ action: a.action, params: a.params });
      const outs = edges.filter((e) => e.source === nodeId);
      for (const e of outs) walk(e.target, path, conditions);
    }
  }

  for (const t of nodes.filter((n) => n.type === "trigger")) {
    const td = t.data as TriggerData;
    const outs = edges.filter((e) => e.source === t.id);
    for (const e of outs) {
      const acc: any[] = [];
      const conds: any[] = [];
      walk(e.target, acc, conds);
      out.push({
        when: td.trigger,
        ...(td.intent ? { intent: td.intent } : {}),
        conditions: conds,
        do: acc,
      });
    }
  }

  return out;
}

function invert(op: ConditionOp): ConditionOp {
  switch (op) {
    case "equals":   return "contains";  // crude but readable
    case "exists":   return "exists";
    case "contains": return "equals";
    case "gt":       return "lt";
    case "lt":       return "gt";
  }
}

/* ========================================================================
 * Initial graph
 * ======================================================================*/

const INITIAL_NODES: FlowNode[] = [
  { id: "trigger-1", type: "trigger", position: { x: 40, y: 80 },
    data: { kind: "trigger", trigger: "call_start" } },
  { id: "cond-1", type: "condition", position: { x: 280, y: 80 },
    data: { kind: "condition", field: "intent.last", op: "equals", value: "pricing" } },
  { id: "act-1", type: "action", position: { x: 560, y: 0 },
    data: { kind: "action", action: "transfer", params: { ingroup: "SALES", summary: "Pricing intent" } } },
  { id: "act-2", type: "action", position: { x: 560, y: 160 },
    data: { kind: "action", action: "say", params: { text: "Got it — let me check that for you." } } },
];

const INITIAL_EDGES: Edge[] = [
  { id: "e1", source: "trigger-1", target: "cond-1" },
  { id: "e2", source: "cond-1",    target: "act-1", sourceHandle: "yes", label: "yes" },
  { id: "e3", source: "cond-1",    target: "act-2", sourceHandle: "no",  label: "no"  },
];

/* ========================================================================
 * Component
 * ======================================================================*/

export function ScenariosTab() {
  const { setValue, getValues } = useFormContext<AgentCreateInput>();

  // Hydrate from form state (round-trips after save).
  const initial = useMemo<{ nodes: FlowNode[]; edges: Edge[] }>(() => {
    const tree = (getValues("scenario_tree") as ScenarioTree) || { rules: [] };
    if (tree.graph && Array.isArray(tree.graph.nodes) && tree.graph.nodes.length > 0) {
      return { nodes: tree.graph.nodes as FlowNode[], edges: tree.graph.edges ?? [] };
    }
    return { nodes: INITIAL_NODES, edges: INITIAL_EDGES };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const [nodes, setNodes] = useState<FlowNode[]>(initial.nodes);
  const [edges, setEdges] = useState<Edge[]>(initial.edges);
  const [selected, setSelected] = useState<FlowNode | null>(null);
  const [showCompiled, setShowCompiled] = useState(false);
  const wrapper = useRef<HTMLDivElement>(null);

  // Persist into the form whenever the graph changes.
  useEffect(() => {
    const compiled = compileGraph(nodes, edges);
    const tree: ScenarioTree = { rules: compiled, graph: { nodes, edges } };
    setValue("scenario_tree", tree as any, { shouldDirty: true });
  }, [nodes, edges, setValue]);

  const onConnect = useCallback(
    (params: Connection) => setEdges((es) => addEdge(params, es)),
    [],
  );

  const addNode = (type: "trigger" | "condition" | "action", at?: { x: number; y: number }) => {
    const pos = at ?? { x: 200 + Math.random() * 200, y: 200 + Math.random() * 100 };
    const id = `${type}-${Date.now()}`;
    let data: NodeData;
    if (type === "trigger") {
      data = { kind: "trigger", trigger: "call_start" };
    } else if (type === "condition") {
      data = { kind: "condition", field: "lead.state", op: "equals", value: "" };
    } else {
      data = { kind: "action", action: "say", params: { text: "" } };
    }
    setNodes((ns) => [...ns, { id, type, position: pos, data }]);
  };

  const onDragStart = (e: React.DragEvent, type: string) => {
    e.dataTransfer.setData("application/x-scenario-node", type);
    e.dataTransfer.effectAllowed = "move";
  };

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault();
    const type = e.dataTransfer.getData("application/x-scenario-node");
    if (!type || !wrapper.current) return;
    const bounds = wrapper.current.getBoundingClientRect();
    addNode(type as any, {
      x: e.clientX - bounds.left - 80,
      y: e.clientY - bounds.top - 20,
    });
  };

  const updateSelected = (patch: Partial<NodeData>) => {
    if (!selected) return;
    setNodes((ns) => ns.map((n) =>
      n.id === selected.id
        ? { ...n, data: { ...n.data, ...patch } as NodeData }
        : n,
    ));
    setSelected({ ...selected, data: { ...selected.data, ...patch } as NodeData });
  };

  const deleteSelected = () => {
    if (!selected) return;
    setNodes((ns) => ns.filter((n) => n.id !== selected.id));
    setEdges((es) => es.filter((e) => e.source !== selected.id && e.target !== selected.id));
    setSelected(null);
  };

  return (
    <div className="grid grid-cols-1 lg:grid-cols-[1fr_300px] gap-6">
      <Card className="p-0 h-[560px] overflow-hidden relative" ref={wrapper}>
        <div
          className="h-full w-full"
          onDragOver={(e) => { e.preventDefault(); e.dataTransfer.dropEffect = "move"; }}
          onDrop={onDrop}
        >
          <ReactFlow
            nodes={nodes}
            edges={edges}
            nodeTypes={NODE_TYPES}
            onNodesChange={(c) => setNodes((n) => applyNodeChanges(c, n) as FlowNode[])}
            onEdgesChange={(c) => setEdges((e) => applyEdgeChanges(c, e))}
            onConnect={onConnect}
            onNodeClick={(_e, n) => setSelected(n as FlowNode)}
            onPaneClick={() => setSelected(null)}
            fitView
          >
            <Background gap={16} />
            <Controls showInteractive={false} />
            <MiniMap pannable zoomable />
          </ReactFlow>
        </div>

        {selected && (
          <NodeConfigDrawer
            node={selected}
            onChange={updateSelected}
            onDelete={deleteSelected}
            onClose={() => setSelected(null)}
          />
        )}
      </Card>

      <div className="space-y-4">
        <Card className="p-4 space-y-3">
          <h3 className="text-sm font-semibold text-slate-900">Node palette</h3>
          <p className="text-xs text-slate-500">Drag onto the canvas, or click to add at random.</p>
          <div className="space-y-2">
            {[
              ["trigger",   "Trigger",   "bg-indigo-50 border-indigo-300 text-indigo-900"],
              ["condition", "Condition", "bg-amber-50 border-amber-300 text-amber-900"],
              ["action",    "Action",    "bg-emerald-50 border-emerald-300 text-emerald-900"],
            ].map(([type, label, cls]) => (
              <div
                key={type as string}
                draggable
                onDragStart={(e) => onDragStart(e, type as string)}
                onClick={() => addNode(type as any)}
                className={`rounded-md border ${cls} px-3 py-2 text-sm cursor-grab select-none`}
              >
                {label}
              </div>
            ))}
          </div>
        </Card>

        <Card className="p-4 space-y-3">
          <h3 className="text-sm font-semibold text-slate-900">Compiled rules</h3>
          <p className="text-xs text-slate-500">
            What the worker sees — emitted from your graph each time it changes.
            Saved to the agent's <code className="text-[10px]">scenario_tree.rules</code>.
          </p>
          <Button type="button" variant="secondary" size="sm"
                  onClick={() => setShowCompiled((v) => !v)} className="w-full">
            <Code className="h-4 w-4" />
            {showCompiled ? "Hide JSON" : "Preview JSON"}
          </Button>
          {showCompiled && (
            <pre className="max-h-64 overflow-auto rounded bg-slate-900 p-2 text-[10px] text-slate-100">
              {JSON.stringify(compileGraph(nodes, edges), null, 2)}
            </pre>
          )}
        </Card>
      </div>
    </div>
  );
}

/* ========================================================================
 * NodeConfigDrawer — edits the selected node in place
 * ======================================================================*/

function NodeConfigDrawer({
  node, onChange, onDelete, onClose,
}: {
  node: FlowNode;
  onChange: (patch: Partial<NodeData>) => void;
  onDelete: () => void;
  onClose: () => void;
}) {
  return (
    <div className="absolute right-0 top-0 h-full w-[300px] border-l border-slate-200 bg-white p-4 shadow-lg overflow-y-auto">
      <div className="flex items-center justify-between mb-3">
        <h4 className="text-sm font-semibold capitalize">{node.type} node</h4>
        <button onClick={onClose} type="button" className="text-slate-400 hover:text-slate-700">
          <X className="h-4 w-4" />
        </button>
      </div>

      {node.type === "trigger" && (
        <TriggerEditor data={node.data as TriggerData} onChange={onChange} />
      )}
      {node.type === "condition" && (
        <ConditionEditor data={node.data as ConditionData} onChange={onChange} />
      )}
      {node.type === "action" && (
        <ActionEditor data={node.data as ActionData} onChange={onChange} />
      )}

      <Button
        type="button" variant="outline" size="sm"
        onClick={onDelete}
        className="mt-4 w-full text-red-600 hover:text-red-700"
      >
        <Trash2 className="h-3.5 w-3.5" /> Delete node
      </Button>
    </div>
  );
}

function TriggerEditor({ data, onChange }: {
  data: TriggerData; onChange: (p: Partial<NodeData>) => void;
}) {
  return (
    <div className="space-y-3">
      <div className="space-y-1.5">
        <Label>Fires on</Label>
        <Select
          value={data.trigger}
          onValueChange={(v) => onChange({ trigger: v as TriggerKind } as any)}
        >
          <SelectTrigger><SelectValue /></SelectTrigger>
          <SelectContent>
            {Object.entries(TRIGGER_LABELS).map(([k, l]) => (
              <SelectItem key={k} value={k}>{l}</SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      {data.trigger === "intent_detected" && (
        <div className="space-y-1.5">
          <Label>Intent name</Label>
          <Input
            value={data.intent ?? ""}
            placeholder="e.g. pricing, objection_price, ready_to_buy"
            onChange={(e) => onChange({ intent: e.target.value } as any)}
          />
        </div>
      )}
    </div>
  );
}

function ConditionEditor({ data, onChange }: {
  data: ConditionData; onChange: (p: Partial<NodeData>) => void;
}) {
  return (
    <div className="space-y-3">
      <div className="space-y-1.5">
        <Label>Field</Label>
        <Input
          value={data.field}
          placeholder="lead.state, transcript.last_intent, vars.budget"
          onChange={(e) => onChange({ field: e.target.value } as any)}
        />
      </div>
      <div className="space-y-1.5">
        <Label>Operator</Label>
        <Select
          value={data.op}
          onValueChange={(v) => onChange({ op: v as ConditionOp } as any)}
        >
          <SelectTrigger><SelectValue /></SelectTrigger>
          <SelectContent>
            <SelectItem value="equals">equals</SelectItem>
            <SelectItem value="contains">contains</SelectItem>
            <SelectItem value="exists">exists</SelectItem>
            <SelectItem value="gt">greater than</SelectItem>
            <SelectItem value="lt">less than</SelectItem>
          </SelectContent>
        </Select>
      </div>
      {data.op !== "exists" && (
        <div className="space-y-1.5">
          <Label>Value</Label>
          <Input
            value={data.value}
            onChange={(e) => onChange({ value: e.target.value } as any)}
          />
        </div>
      )}
      <p className="text-xs text-slate-500">
        Wire <strong>yes</strong> from the top right handle, <strong>no</strong> from the bottom right.
      </p>
    </div>
  );
}

function ActionEditor({ data, onChange }: {
  data: ActionData; onChange: (p: Partial<NodeData>) => void;
}) {
  const params = data.params || {};
  const updateParam = (k: string, v: string) =>
    onChange({ params: { ...params, [k]: v } } as any);
  return (
    <div className="space-y-3">
      <div className="space-y-1.5">
        <Label>Action</Label>
        <Select
          value={data.action}
          onValueChange={(v) => onChange({ action: v as ActionKind, params: {} } as any)}
        >
          <SelectTrigger><SelectValue /></SelectTrigger>
          <SelectContent>
            {Object.entries(ACTION_LABELS).map(([k, l]) => (
              <SelectItem key={k} value={k}>{l}</SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      {ACTION_PARAM_HINTS[data.action].map(({ key, label }) => (
        <div key={key} className="space-y-1.5">
          <Label>{label}</Label>
          {key === "text" || key === "summary" || key === "notes" ? (
            <Textarea
              rows={2}
              value={params[key] ?? ""}
              onChange={(e) => updateParam(key, e.target.value)}
            />
          ) : (
            <Input
              value={params[key] ?? ""}
              onChange={(e) => updateParam(key, e.target.value)}
            />
          )}
        </div>
      ))}
      <Button
        type="button" variant="ghost" size="sm" className="w-full"
        onClick={() => updateParam(`extra_${Object.keys(params).length}`, "")}
      >
        <Plus className="h-3.5 w-3.5" /> Add custom parameter
      </Button>
    </div>
  );
}
