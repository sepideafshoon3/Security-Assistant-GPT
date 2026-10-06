import { useState } from "react";
import type { Project } from "../App";
import { Check, FolderPlus, Plus, X } from "lucide-react";
import {
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
} from "./ui/dropdown-menu";
import { Input } from "./ui/input";

interface ProjectSubmenuProps {
  projects: Project[];
  currentProjectId: string | null | undefined;
  onAssign: (projectId: string | null) => void;
  onCreateProject: (name: string) => Promise<Project | null>;
}

/** "Add to project" submenu: pick an existing project, clear the current
 * one, or create a new one inline — shared by the sidebar row menu and the
 * chat header menu so the two stay in sync. */
export function ProjectSubmenu({
  projects,
  currentProjectId,
  onAssign,
  onCreateProject,
}: ProjectSubmenuProps) {
  const [isCreating, setIsCreating] = useState(false);
  const [newName, setNewName] = useState("");
  const [isSaving, setIsSaving] = useState(false);

  const commitCreate = async () => {
    const trimmed = newName.trim();
    if (!trimmed || isSaving) return;
    setIsSaving(true);
    const created = await onCreateProject(trimmed);
    setIsSaving(false);
    setNewName("");
    setIsCreating(false);
    if (created) onAssign(created.id);
  };

  return (
    <DropdownMenuSub>
      <DropdownMenuSubTrigger onClick={(e) => e.stopPropagation()}>
        <FolderPlus className="w-3.5 h-3.5" aria-hidden />
        {currentProjectId ? "Move to project" : "Add to project"}
      </DropdownMenuSubTrigger>
      <DropdownMenuSubContent className="w-56" onClick={(e) => e.stopPropagation()}>
        {currentProjectId && (
          <>
            <DropdownMenuItem onSelect={() => onAssign(null)}>
              <X className="w-3.5 h-3.5" aria-hidden />
              Remove from project
            </DropdownMenuItem>
            <DropdownMenuSeparator />
          </>
        )}

        {projects.length === 0 && !isCreating && (
          <p className="px-2 py-1.5 text-xs text-fg-faint">No projects yet.</p>
        )}

        {projects.map((project) => (
          <DropdownMenuItem key={project.id} onSelect={() => onAssign(project.id)}>
            {project.id === currentProjectId ? (
              <Check className="w-3.5 h-3.5" aria-hidden />
            ) : (
              <span className="w-3.5 h-3.5 shrink-0" aria-hidden />
            )}
            <span className="truncate">{project.name}</span>
          </DropdownMenuItem>
        ))}

        <DropdownMenuSeparator />

        {isCreating ? (
          <div className="px-2 py-1.5">
            <Input
              autoFocus
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              onKeyDown={(e) => {
                e.stopPropagation();
                if (e.key === "Enter") {
                  e.preventDefault();
                  void commitCreate();
                } else if (e.key === "Escape") {
                  e.preventDefault();
                  setIsCreating(false);
                  setNewName("");
                }
              }}
              placeholder="Project name"
              className="h-7 text-sm"
              disabled={isSaving}
            />
          </div>
        ) : (
          <DropdownMenuItem
            onSelect={(e) => {
              e.preventDefault();
              setIsCreating(true);
            }}
          >
            <Plus className="w-3.5 h-3.5" aria-hidden />
            New project…
          </DropdownMenuItem>
        )}
      </DropdownMenuSubContent>
    </DropdownMenuSub>
  );
}
