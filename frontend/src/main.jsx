import React, { createContext, useContext, useEffect, useState } from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter, Routes, Route, NavLink, Navigate, useNavigate } from 'react-router-dom'
import { api, auth } from './api'
import './styles.css'
import Login from './pages/Login'
import Dashboard from './pages/Dashboard'
import Loans from './pages/Loans'
import LoanDetail from './pages/LoanDetail'
import NewLoan from './pages/NewLoan'
import Lease3W from './pages/Lease3W'
import Customers from './pages/Customers'
import Products from './pages/Products'
import Migration from './pages/Migration'
import Data from './pages/Data'
import Soa from './pages/Soa'
import Quote from './pages/Quote'
import Dpd from './pages/Dpd'
import Reports from './pages/Reports'
import Users from './pages/Users'

const UserCtx = createContext(null)
export const useUser = () => useContext(UserCtx)

function Shell() {
  const [user, setUser] = useState(null)
  const [ready, setReady] = useState(false)
  const nav = useNavigate()
  useEffect(() => {
    if (!auth.token) { setReady(true); return }
    api('/auth/me').then(setUser).catch(() => auth.set(null)).finally(() => setReady(true))
  }, [])
  if (!ready) return null
  if (!user) return <Login onIn={u => { setUser(u); nav('/') }} />
  const isAdmin = user.role === 'ADMIN'
  return (
    <UserCtx.Provider value={user}>
      <div className="shell">
        <nav className="side" aria-label="Main">
          <div className="brand"><span className="brand-mark" aria-hidden="true" />Loan Ledger</div>
          <NavLink to="/" end>Portfolio</NavLink>
          <NavLink to="/loans">Loans</NavLink>
          <NavLink to="/loans/new">Book a loan</NavLink>
          {user.role !== 'VIEWER' && <NavLink to="/lease3w">3-wheeler lease</NavLink>}
          <NavLink to="/customers">Customers</NavLink>
          <NavLink to="/products">Products</NavLink>
          {user.role !== 'VIEWER' && <NavLink to="/data">Data</NavLink>}
          <NavLink to="/dpd">DPD calculator</NavLink>
          {user.role !== 'VIEWER' && <NavLink to="/reports">Reports</NavLink>}
          {isAdmin && <NavLink to="/users">Users</NavLink>}
          {isAdmin && <NavLink to="/migration">M2P migration &amp; EOD</NavLink>}
          <div className="grow" />
          <div className="who">
            <div style={{ color: '#fff' }}>{user.full_name || user.username}</div>
            <div className="small">Role: {user.role.toLowerCase()}</div>
            <button className="link small" onClick={() => { auth.set(null); setUser(null) }}>Sign out</button>
          </div>
        </nav>
        <main className="main">
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/loans" element={<Loans />} />
            <Route path="/loans/new" element={<NewLoan />} />
            <Route path="/lease3w" element={<Lease3W />} />
            <Route path="/loans/:id" element={<LoanDetail />} />
            <Route path="/loans/:id/soa" element={<Soa />} />
            <Route path="/loans/:id/quote" element={<Quote />} />
            <Route path="/customers" element={<Customers />} />
            <Route path="/products" element={<Products />} />
            <Route path="/data" element={<Data />} />
            <Route path="/dpd" element={<Dpd />} />
            <Route path="/reports" element={<Reports />} />
            {isAdmin && <Route path="/users" element={<Users />} />}
            {isAdmin && <Route path="/migration" element={<Migration />} />}
            <Route path="*" element={<Navigate to="/" />} />
          </Routes>
        </main>
      </div>
    </UserCtx.Provider>
  )
}

ReactDOM.createRoot(document.getElementById('root')).render(
  <BrowserRouter><Shell /></BrowserRouter>
)
