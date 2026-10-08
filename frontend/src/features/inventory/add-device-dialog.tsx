import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Loader2, Plus } from 'lucide-react'
import { useState, type ReactNode } from 'react'
import { useNavigate } from 'react-router'
import { api, type NewDevice } from '@/api'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { rememberName, savedName } from '@/lib/your-name'
import { problemWith, splitAliases } from './add-device-rules'
import { platformName } from './labels'

// Add a device to AINOPS. No password is ever typed here: the device names a login profile
// that is already in the server's .env. Added devices go to lab/inventory.local.yaml.

const NEW_SITE = '__new__'
const selectClass =
  'h-9 w-full rounded-md border bg-background px-2 text-sm focus-visible:ring-[3px] focus-visible:ring-ring/50 focus-visible:outline-none'

function Field({
  id,
  label,
  hint,
  children,
}: {
  id: string
  label: string
  hint?: string
  children: ReactNode
}) {
  return (
    <div className="space-y-1">
      <label htmlFor={id} className="text-xs font-semibold">
        {label}
      </label>
      {children}
      {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
    </div>
  )
}

export function AddDeviceDialog() {
  const [open, setOpen] = useState(false)
  const options = useQuery({
    queryKey: ['inventory', 'options'],
    queryFn: api.inventoryOptions,
    enabled: open,
  })
  const [name, setName] = useState('')
  const [site, setSite] = useState('')
  const [newSite, setNewSite] = useState('')
  const [siteName, setSiteName] = useState('')
  const [role, setRole] = useState('')
  const [platform, setPlatform] = useState('cisco_ios')
  const [port, setPort] = useState('')
  const [aliases, setAliases] = useState('')
  const [description, setDescription] = useState('')
  const [profile, setProfile] = useState('')
  const [addedBy, setAddedBy] = useState(savedName)
  const queryClient = useQueryClient()
  const navigate = useNavigate()

  const sites = options.data?.sites ?? {}
  const chosenSite = site === NEW_SITE ? newSite.trim().toUpperCase() : site
  const device: NewDevice = {
    name: name.trim(),
    site: chosenSite,
    ...(site === NEW_SITE ? { site_name: siteName.trim() } : {}),
    role: role.trim(),
    platform,
    port: Number(port),
    aliases: splitAliases(aliases),
    description: description.trim(),
    credential_ref: profile || null,
    added_by: addedBy.trim(),
  }
  const problem = problemWith(device, Object.keys(sites))
  const add = useMutation({
    mutationFn: () => api.addDevice(device),
    onSuccess: (row) => {
      rememberName(device.added_by)
      void queryClient.invalidateQueries({ queryKey: ['inventory'] })
      setOpen(false)
      void navigate(`/inventory/${encodeURIComponent(row.name)}`)
    },
  })

  return (
    <>
      <Button onClick={() => setOpen(true)}>
        <Plus aria-hidden="true" /> Add device
      </Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-h-[90svh] overflow-y-auto sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>Add a device</DialogTitle>
            <DialogDescription>
              AINOPS will be able to log in to it, read-only, with the login profile you choose. It
              joins the network map at the next discovery.
            </DialogDescription>
          </DialogHeader>
          <form
            id="add-device"
            onSubmit={(event) => {
              event.preventDefault()
              if (!problem && !add.isPending) add.mutate()
            }}
            className="grid gap-3 sm:grid-cols-2"
          >
            <Field id="device-name" label="Name">
              <Input
                id="device-name"
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="e.g. BLR-WAN-RTR-1"
                maxLength={63}
              />
            </Field>
            <Field
              id="device-aliases"
              label="Other names (optional)"
              hint="Comma-separated, up to 5."
            >
              <Input
                id="device-aliases"
                value={aliases}
                onChange={(e) => setAliases(e.target.value)}
                placeholder="e.g. BLR-P2P"
              />
            </Field>
            <Field id="device-site" label="Site">
              <select
                id="device-site"
                value={site}
                onChange={(e) => setSite(e.target.value)}
                className={selectClass}
              >
                <option value="">Choose a site</option>
                {Object.entries(sites).map(([code, label]) => (
                  <option key={code} value={code}>
                    {code} · {label}
                  </option>
                ))}
                <option value={NEW_SITE}>New site…</option>
              </select>
            </Field>
            {site === NEW_SITE ? (
              <div className="grid grid-cols-[6rem_minmax(0,1fr)] gap-2">
                <Field id="site-code" label="Site code">
                  <Input
                    id="site-code"
                    value={newSite}
                    onChange={(e) => setNewSite(e.target.value)}
                    placeholder="BLR"
                    maxLength={10}
                  />
                </Field>
                <Field id="site-name" label="Site name">
                  <Input
                    id="site-name"
                    value={siteName}
                    onChange={(e) => setSiteName(e.target.value)}
                    placeholder="Bengaluru"
                    maxLength={60}
                  />
                </Field>
              </div>
            ) : (
              <div className="hidden sm:block" />
            )}
            <Field id="device-role" label="Role">
              <Input
                id="device-role"
                list="device-roles"
                value={role}
                onChange={(e) => setRole(e.target.value)}
                placeholder="e.g. wan-router"
                maxLength={31}
              />
              <datalist id="device-roles">
                {(options.data?.roles ?? []).map((r) => (
                  <option key={r} value={r} />
                ))}
              </datalist>
            </Field>
            <Field id="device-platform" label="Vendor / OS">
              <select
                id="device-platform"
                value={platform}
                onChange={(e) => setPlatform(e.target.value)}
                className={selectClass}
              >
                {(options.data?.platforms ?? ['cisco_ios', 'juniper_junos']).map((p) => (
                  <option key={p} value={p}>
                    {platformName(p)}
                  </option>
                ))}
              </select>
            </Field>
            <Field
              id="device-port"
              label="EVE-NG console port"
              hint="In the lab. A real network uses a management address."
            >
              <Input
                id="device-port"
                inputMode="numeric"
                value={port}
                onChange={(e) => setPort(e.target.value)}
                placeholder="e.g. 32780"
              />
            </Field>
            <Field
              id="device-profile"
              label="Login profile"
              hint="From the server's .env. Never type a password here: ask whoever runs AINOPS to add a profile."
            >
              <select
                id="device-profile"
                value={profile}
                onChange={(e) => setProfile(e.target.value)}
                className={selectClass}
              >
                <option value="">None (the console needs no login)</option>
                {(options.data?.credential_profiles ?? []).map((p) => (
                  <option key={p} value={p}>
                    {p}
                  </option>
                ))}
              </select>
            </Field>
            <div className="sm:col-span-2">
              <Field id="device-description" label="Description (optional)">
                <Input
                  id="device-description"
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  placeholder="e.g. Bengaluru end of the BLR-MAA leased line"
                  maxLength={200}
                />
              </Field>
            </div>
            <div className="sm:col-span-2">
              <Field id="device-added-by" label="Your name">
                <Input
                  id="device-added-by"
                  value={addedBy}
                  onChange={(e) => setAddedBy(e.target.value)}
                  maxLength={80}
                  autoComplete="name"
                />
              </Field>
            </div>
          </form>
          {add.isError ? (
            <p role="alert" className="text-sm text-status-critical">
              Not added: {add.error.message}
            </p>
          ) : (
            problem && <p className="text-xs text-muted-foreground">{problem}</p>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button type="submit" form="add-device" disabled={Boolean(problem) || add.isPending}>
              {add.isPending && (
                <Loader2 aria-hidden="true" className="animate-spin motion-reduce:animate-none" />
              )}
              Add device
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  )
}
