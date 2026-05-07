import { useFormContext, Controller } from "react-hook-form";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import type { AgentCreateInput } from "@/lib/validation";

export function PersonaTab() {
  const { register, control, watch, formState: { errors } } = useFormContext<AgentCreateInput>();
  const persona = watch("persona");

  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
      <Card className="lg:col-span-2">
        <CardHeader>
          <CardTitle>Persona</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <Field label="Name" error={errors.persona?.name?.message}>
            <Input {...register("persona.name")} placeholder="e.g. Sam from Acme" />
          </Field>

          <div className="grid grid-cols-3 gap-4">
            <Field label="Age range" error={errors.persona?.age_range?.message}>
              <Controller
                name="persona.age_range"
                control={control}
                render={({ field }) => (
                  <Select value={field.value} onValueChange={field.onChange}>
                    <SelectTrigger><SelectValue placeholder="Pick range" /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="20-30">20–30</SelectItem>
                      <SelectItem value="30-40">30–40</SelectItem>
                      <SelectItem value="40-50">40–50</SelectItem>
                      <SelectItem value="50+">50+</SelectItem>
                    </SelectContent>
                  </Select>
                )}
              />
            </Field>
            <Field label="Gender" error={errors.persona?.gender?.message}>
              <Controller
                name="persona.gender"
                control={control}
                render={({ field }) => (
                  <Select value={field.value} onValueChange={field.onChange}>
                    <SelectTrigger><SelectValue placeholder="Pick" /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="female">Female</SelectItem>
                      <SelectItem value="male">Male</SelectItem>
                      <SelectItem value="neutral">Neutral</SelectItem>
                    </SelectContent>
                  </Select>
                )}
              />
            </Field>
            <Field label="Accent" error={errors.persona?.accent?.message}>
              <Input {...register("persona.accent")} placeholder="e.g. neutral US" />
            </Field>
          </div>

          <Field label="Backstory" error={errors.persona?.backstory?.message}>
            <Textarea
              {...register("persona.backstory")}
              rows={4}
              placeholder="Two-paragraph backstory: where they work, what they've done, why they're calling."
            />
          </Field>

          <Field label="Additional guidelines" error={errors.persona?.guidelines?.message}>
            <Textarea
              {...register("persona.guidelines")}
              rows={3}
              placeholder="e.g. Always confirm name before pitching. Never quote a price below $500."
            />
          </Field>

          <Field label="If asked: 'are you a robot?'" error={errors.persona?.disclosure_response?.message}>
            <Textarea
              {...register("persona.disclosure_response")}
              rows={2}
              placeholder="Honest disclosure response."
            />
          </Field>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>LLM preview</CardTitle>
        </CardHeader>
        <CardContent>
          <pre className="text-xs whitespace-pre-wrap rounded-md bg-slate-50 p-3 text-slate-700 leading-5">
{`You are ${persona?.name || "<name>"}, ${persona?.age_range || "?"} ${
  persona?.gender || "?"} with a ${persona?.accent || "?"} accent.

${persona?.backstory || "<backstory>"}

${persona?.guidelines ? `Guidelines:\n${persona.guidelines}\n` : ""}If asked if you are a bot, you respond:
"${persona?.disclosure_response || "<honest disclosure>"}"`}
          </pre>
        </CardContent>
      </Card>
    </div>
  );
}

function Field({
  label, children, error,
}: { label: string; children: React.ReactNode; error?: string }) {
  return (
    <div className="space-y-1.5">
      <Label>{label}</Label>
      {children}
      {error && <p className="text-xs text-rose-600">{error}</p>}
    </div>
  );
}
