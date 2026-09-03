-- Migration 004 - Auto-create workspace for new users

-- Function to handle new user signup
CREATE OR REPLACE FUNCTION public.handle_new_user_workspace()
RETURNS trigger AS $$
DECLARE
  new_workspace_id uuid;
BEGIN
  -- Insert a new workspace for the user
  INSERT INTO public.workspaces (name)
  VALUES (COALESCE(NEW.email, 'User') || '''s Workspace')
  RETURNING id INTO new_workspace_id;

  -- Add the user to the workspace members
  INSERT INTO public.workspace_members (workspace_id, user_id)
  VALUES (new_workspace_id, NEW.id);

  RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- Trigger to run the function after a user is inserted into auth.users
DROP TRIGGER IF EXISTS on_auth_user_created_workspace ON auth.users;
CREATE TRIGGER on_auth_user_created_workspace
  AFTER INSERT ON auth.users
  FOR EACH ROW EXECUTE FUNCTION public.handle_new_user_workspace();
