import { useFieldArray, useFormContext } from "react-hook-form";
import { Plus, Trash2 } from "lucide-react";
import Editor from "@monaco-editor/react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import type { AgentCreateInput } from "@/lib/validation";

export function ScriptTab() {
  const { control, register, watch } = useFormContext<AgentCreateInput>();

  const openings = useFieldArray({ control, name: "script.opening_variants" as never });
  const sections = useFieldArray({ control, name: "script.sections" });
  const objections = useFieldArray({ control, name: "script.objections" });

  const closing = watch("script.closing");

  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
      <div className="lg:col-span-2 space-y-6">
        {/* Opening variants */}
        <Card>
          <CardHeader>
            <CardTitle>Openings</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {openings.fields.map((f, i) => (
              <div key={f.id} className="flex gap-2">
                <Input
                  {...register(`script.opening_variants.${i}` as const)}
                  placeholder={`Variant ${i + 1}`}
                />
                <Button
                  type="button" variant="ghost" size="icon"
                  onClick={() => openings.remove(i)}
                  disabled={openings.fields.length <= 1}
                >
                  <Trash2 className="h-4 w-4" />
                </Button>
              </div>
            ))}
            <Button
              type="button" variant="outline" size="sm"
              onClick={() => openings.append("")}
            >
              <Plus className="h-4 w-4" /> Add opening variant
            </Button>
          </CardContent>
        </Card>

        {/* Sections */}
        <Card>
          <CardHeader>
            <CardTitle>Sections</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {sections.fields.length === 0 && (
              <p className="text-sm text-slate-400">No sections yet.</p>
            )}
            {sections.fields.map((f, i) => (
              <div key={f.id} className="rounded-md border border-slate-200 p-3 space-y-2">
                <div className="flex gap-2">
                  <Input
                    {...register(`script.sections.${i}.title` as const)}
                    placeholder="Section title"
                  />
                  <Button
                    type="button" variant="ghost" size="icon"
                    onClick={() => sections.remove(i)}
                  >
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </div>
                <Editor
                  height="120px"
                  defaultLanguage="markdown"
                  defaultValue={(f as any).content ?? ""}
                  onChange={(v) =>
                    sections.update(i, {
                      ...(f as any),
                      content: v ?? "",
                    } as any)
                  }
                  options={{
                    minimap: { enabled: false },
                    lineNumbers: "off",
                    folding: false,
                    wordWrap: "on",
                    fontSize: 13,
                  }}
                />
                <p className="text-[11px] text-slate-400">
                  Variables like <code>{"{{lead.name}}"}</code> are interpolated at call time.
                </p>
              </div>
            ))}
            <Button
              type="button" variant="outline" size="sm"
              onClick={() =>
                sections.append({
                  id: `s-${Date.now()}`,
                  title: "New section",
                  content: "",
                  expected_response_keywords: [],
                })
              }
            >
              <Plus className="h-4 w-4" /> Add section
            </Button>
          </CardContent>
        </Card>

        {/* Closing */}
        <Card>
          <CardHeader>
            <CardTitle>Closing</CardTitle>
          </CardHeader>
          <CardContent>
            <Textarea
              {...register("script.closing")}
              rows={3}
              placeholder="Wrap-up line. e.g. 'Thanks for your time — have a great day.'"
            />
          </CardContent>
        </Card>

        {/* Objections */}
        <Card>
          <CardHeader>
            <CardTitle>Objections library</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {objections.fields.length === 0 && (
              <p className="text-sm text-slate-400">No objections defined.</p>
            )}
            {objections.fields.map((f, i) => (
              <div key={f.id} className="grid grid-cols-[1fr_2fr_auto] gap-2 items-start">
                <Input
                  {...register(`script.objections.${i}.trigger` as const)}
                  placeholder="When customer says..."
                />
                <Textarea
                  {...register(`script.objections.${i}.response` as const)}
                  rows={2}
                  placeholder="Agent's reply"
                />
                <Button
                  type="button" variant="ghost" size="icon"
                  onClick={() => objections.remove(i)}
                >
                  <Trash2 className="h-4 w-4" />
                </Button>
              </div>
            ))}
            <Button
              type="button" variant="outline" size="sm"
              onClick={() =>
                objections.append({
                  id: `o-${Date.now()}`,
                  trigger: "",
                  response: "",
                })
              }
            >
              <Plus className="h-4 w-4" /> Add objection
            </Button>
          </CardContent>
        </Card>
      </div>

      {/* Sandbox */}
      <Card>
        <CardHeader>
          <CardTitle>Sandbox</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <p className="text-xs text-slate-500">
            Type something a customer might say and see how the LLM would respond
            given the current script. (Wires up to <code>/api/v1/agents/&lt;id&gt;/test-call</code>
            in a follow-up.)
          </p>
          <Textarea rows={4} placeholder="Customer line…" />
          <Button type="button" variant="secondary">Run</Button>
          <div className="rounded-md bg-slate-50 p-3 text-sm text-slate-500 italic">
            Closing preview:
            <p className="not-italic text-slate-700 mt-1">
              {closing || "—"}
            </p>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
