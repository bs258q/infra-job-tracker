export type Role = {
  id: string
  company: string
  title: string
  url: string
  locations: string[]
  regions: string[]
  remote: boolean
  workplace?: string
  categories: string[]
  level: string
  posted: string | null
  postedApprox: boolean
  firstSeen: string
  salary: string
  salaryMin: number | null
  salaryMax: number | null
  source: string
  postings: number
}

export type Facets = {
  categories: string[]
  regions: string[]
  levels: string[]
  workplaces: string[]
}

export type JobsData = {
  generatedAt: string
  companiesTracked: number
  errors: Record<string, string>
  facets?: Facets
  roles: Role[]
}

export type Profile = {
  id: string
  name: string
  description: string
}

export const NOT_STATED = 'Not stated'

export type HistoryPoint = {
  date: string
  total: number
  new: number
  byCompany: Record<string, number>
  byCategory: Record<string, number>
}

export const STATUSES = ['saved', 'applied', 'interviewing', 'offer', 'rejected', 'hidden'] as const
export type Status = (typeof STATUSES)[number]

export const STATUS_LABEL: Record<Status, string> = {
  saved: 'Saved',
  applied: 'Applied',
  interviewing: 'Interviewing',
  offer: 'Offer',
  rejected: 'Rejected',
  hidden: 'Not interested',
}

export type Tracked = {
  status: Status
  updatedAt: string
  note?: string
  company: string
  title: string
  url: string
}

export type PostedWindow = 'any' | '24h' | '7d' | '30d'
export type SortKey = 'newest' | 'salary' | 'company'

export type Filters = {
  q: string
  posted: PostedWindow
  categories: string[]
  levels: string[]
  regions: string[]
  workplaces: string[]
  companies: string[]
  minSalary: number
  salaryOnly: boolean
  newOnly: boolean
  status: 'active' | 'untracked' | Status
  sort: SortKey
}

export const DEFAULT_FILTERS: Filters = {
  q: '',
  posted: 'any',
  categories: [],
  levels: [],
  regions: [],
  workplaces: [],
  companies: [],
  minSalary: 0,
  salaryOnly: false,
  newOnly: false,
  status: 'active',
  sort: 'newest',
}
